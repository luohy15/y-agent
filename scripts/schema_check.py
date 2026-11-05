#!/usr/bin/env python3
"""Check candidate ORM columns against the proven production database.

Run from this checkout: uv run python scripts/schema_check.py
Optional explicit apply: ... schema_check.py apply --file migration/add.sql
Apply supports only simple ADD COLUMN statements with built-in types and literal
 defaults. Other SQL must be reviewed/applied separately, then checked here.
Exit 0: complete; 1: missing columns; 2: proof, connection, or apply failure.
No migration runs in check mode. Exceptions and subprocess output are withheld
because drivers, AWS and psql can include credentials or SQL in their errors.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import pkgutil
import re
import socket
import subprocess
import sys

import boto3
from botocore.config import Config
from dotenv import load_dotenv
import psycopg
from sqlalchemy.engine import make_url


class GateError(Exception):
    pass


@dataclass(frozen=True)
class Target:
    proxy: str
    endpoint: str
    port: int
    database: str


def collect_expected():
    import storage.entity
    from storage.entity.base import Base

    root = Path(__file__).resolve().parents[1] / "storage/src/storage/entity"
    if {Path(path).resolve() for path in storage.entity.__path__} != {root}:
        raise GateError("candidate-import-mismatch")
    for module in pkgutil.walk_packages(storage.entity.__path__, "storage.entity."):
        importlib.import_module(module.name)
    expected = {
        (table.schema or "public", table.name, column.name)
        for table in Base.metadata.tables.values() for column in table.columns
    }
    if not expected:
        raise GateError("metadata-empty")
    return expected


def load_url():
    from storage.global_config import load_global_config

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    load_global_config()
    # Match the checkout's actual storage configuration, including DEV precedence.
    return make_url(os.environ.get("DATABASE_URL_DEV", os.environ.get("DATABASE_URL", "")))


def prove_target(url):
    config = Config(connect_timeout=10, read_timeout=20, retries={"max_attempts": 2})
    session = boto3.Session(region_name="us-east-1")
    lamb = session.client("lambda", config=config)
    rds = session.client("rds", config=config)
    deployed = make_url(lamb.get_function_configuration(FunctionName="y-agent-api")
                        ["Environment"]["Variables"]["DATABASE_URL"])
    proxies = [proxy for page in rds.get_paginator("describe_db_proxies").paginate()
               for proxy in page["DBProxies"] if proxy["Endpoint"] == deployed.host]
    if len(proxies) != 1 or deployed.query:
        raise GateError("endpoint-unproven")
    targets = [target for page in rds.get_paginator("describe_db_proxy_targets").paginate(
        DBProxyName=proxies[0]["DBProxyName"], TargetGroupName="default")
        for target in page["Targets"] if target.get("Type") == "RDS_INSTANCE"]
    if len(targets) != 1 or targets[0].get("TargetHealth", {}).get("State") != "AVAILABLE":
        raise GateError("endpoint-unproven")
    target = targets[0]
    proof = Target(deployed.host, target["Endpoint"], int(target["Port"]), deployed.database)
    if (deployed.port or 5432) != proof.port:
        raise GateError("endpoint-unproven")
    validate_url(url, proof)
    return proof


def validate_url(url, target):
    # Reject libpq routing overrides, multi-host URLs and alternate databases.
    if (url.drivername not in {"postgresql", "postgresql+psycopg"}
            or url.host != target.endpoint or (url.port or 5432) != target.port
            or url.database != target.database or not url.username
            or any(key not in {"sslmode", "sslrootcert"} for key in url.query)
            or url.query.get("sslmode", "require") not in {"require", "verify-ca", "verify-full"}):
        raise GateError("endpoint-unproven")


def connection_args(url):
    return dict(host=url.host, port=url.port or 5432, dbname=url.database,
                user=url.username, password=url.password or "", connect_timeout=10,
                sslmode=url.query.get("sslmode", "require"),
                sslrootcert=url.query.get("sslrootcert", ""))


def read_catalog(url, target):
    validate_url(url, target)
    addresses = {row[4][0] for row in socket.getaddrinfo(target.endpoint, target.port,
                                                       type=socket.SOCK_STREAM)}
    # A new driver connection, never the application's pool or the DDL session.
    with psycopg.connect(**connection_args(url),
                         options="-c default_transaction_read_only=on -c statement_timeout=15000") as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_database(), host(inet_server_addr()), inet_server_port()")
            database, address, port = cursor.fetchone()
            if database != target.database or address not in addresses or port != target.port:
                raise GateError("endpoint-unproven")
            cursor.execute("SELECT table_schema, table_name, column_name FROM information_schema.columns")
            return set(cursor.fetchall())


def validate_additive_sql(sql):
    # Deliberately narrow grammar, not a denylist pretending to parse PostgreSQL.
    # No functions, expressions, quoted identifiers, psql commands, or DO blocks.
    sql = re.sub(r"--[^\n]*", "", sql)
    identifier = r"[a-z_][a-z_0-9]*"
    typename = r"(?:text|boolean|smallint|integer|bigint|int|real|double\s+precision|jsonb?|uuid|date|timestamp(?:\s+with(?:out)?\s+time\s+zone)?|varchar\(\d+\)|numeric(?:\(\d+(?:,\s*\d+)?\))?)"
    literal = r"(?:NULL|true|false|[+-]?\d+(?:\.\d+)?|'[a-zA-Z0-9 _.-]*')"
    statement = rf"ALTER\s+TABLE\s+(?:{identifier}\.)?{identifier}\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?{identifier}\s+{typename}(?:\s+NOT\s+NULL)?(?:\s+DEFAULT\s+{literal})?"
    parts = sql.strip().split(";")
    if parts[-1].strip() == "":
        parts.pop()
    if not parts or any(not re.fullmatch(statement, part.strip(), re.IGNORECASE) for part in parts):
        raise GateError("apply-sql-not-supported-additive")
    if any(re.search(r"\bNOT\s+NULL\b", part, re.IGNORECASE)
           and (not re.search(r"\bDEFAULT\b", part, re.IGNORECASE)
                or re.search(r"\bDEFAULT\s+NULL\s*$", part, re.IGNORECASE)) for part in parts):
        raise GateError("apply-sql-not-supported-additive")


def apply_file(path, url):
    sql = path.read_text()
    validate_additive_sql(sql)
    # Pass the validated bytes, not a path that could change after validation.
    # Remove inherited libpq settings, including PGSERVICE/PGOPTIONS routing.
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    args = connection_args(url)
    for key, value in args.items():
        env[{"dbname": "PGDATABASE", "user": "PGUSER", "password": "PGPASSWORD",
             "host": "PGHOST", "port": "PGPORT", "connect_timeout": "PGCONNECT_TIMEOUT",
             "sslmode": "PGSSLMODE", "sslrootcert": "PGSSLROOTCERT"}[key]] = str(value)
    env["PGOPTIONS"] = "-c search_path=public -c lock_timeout=10000 -c statement_timeout=60000"
    result = subprocess.run(["psql", "-X", "-v", "ON_ERROR_STOP=1", "--single-transaction", "-f", "-"],
                            input=sql, text=True, capture_output=True, env=env, timeout=120)
    if result.returncode:
        raise GateError("apply-failed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("check")
    apply = sub.add_parser("apply")
    apply.add_argument("--file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        expected = collect_expected()
        url = load_url()
        target = prove_target(url)
        catalog = read_catalog(url, target)
        if args.command == "apply":
            apply_file(args.file, url)
            catalog = read_catalog(url, target)
        missing = sorted(expected - catalog)
        print(f"[schema-gate] env=prod db={target.database} "
              f"endpoint=y-agent-api->{target.proxy}->{target.endpoint}:{target.port} "
              f"tables={len({pair[:2] for pair in expected})} columns={len(expected)} missing={len(missing)}")
        for pair in missing:
            print("missing " + ".".join(pair))
        return 1 if missing else 0
    except GateError as exc:
        print(f"[schema-gate] env=prod error={exc}", file=sys.stderr)
    except Exception:
        print("[schema-gate] env=prod error=check-failed (details withheld to protect credentials)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
