#!/usr/bin/env python3
"""Check candidate ORM columns against the proven production database.

Run from this checkout: uv run python scripts/schema_check.py
Optional range: ... schema_check.py --base <rev> --candidate <rev>
A range with no tracked storage/src/storage/entity/** change and no tracked
migration file prints [schema-gate] not-required and exits 0. migration/ is
gitignored, so on-disk SQL is not inspected. Anything else, including no
range, compares ORM columns to the proven production database.
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
        raise GateError("endpoint-unproven:db-proxy")
    targets = [target for page in rds.get_paginator("describe_db_proxy_targets").paginate(
        DBProxyName=proxies[0]["DBProxyName"], TargetGroupName="default")
        for target in page["Targets"] if target.get("Type") == "RDS_INSTANCE"]
    if len(targets) != 1 or targets[0].get("TargetHealth", {}).get("State") != "AVAILABLE":
        raise GateError("endpoint-unproven:proxy-target")
    target = targets[0]
    proof = Target(deployed.host, target["Endpoint"], int(target["Port"]), deployed.database)
    if (deployed.port or 5432) != proof.port:
        raise GateError("endpoint-unproven:target-port")
    validate_url(url, proof)
    return proof


def validate_url(url, target):
    # Reject libpq routing overrides, multi-host URLs and alternate databases.
    if (url.drivername not in {"postgresql", "postgresql+psycopg"}
            or url.host != target.endpoint or (url.port or 5432) != target.port
            or url.database != target.database or not url.username
            or any(key not in {"sslmode", "sslrootcert"} for key in url.query)
            or url.query.get("sslmode", "require") not in {"require", "verify-ca", "verify-full"}):
        raise GateError("endpoint-unproven:database-url")


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
                raise GateError("endpoint-unproven:server-address")
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


_ENTITY_PREFIX = "storage/src/storage/entity/"
_MIGRATION_SQL = re.compile(r"^migration/[0-9]+_.+\.sql$")


def paths_require_schema(paths):
    """True when the tracked diff names an entity path or a tracked migration file.

    ``migration/`` is gitignored, so a file that exists only on disk is never in
    ``paths``. Callers must not describe a false result as "no migration SQL".
    """
    for path in paths:
        if path == "storage/src/storage/entity" or path.startswith(_ENTITY_PREFIX):
            return True
        if _MIGRATION_SQL.fullmatch(path):
            return True
    return False


def changed_paths(base, candidate):
    """Paths added, removed, or renamed between two revisions. Both rename ends count."""
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "-z", "--name-status", "--find-renames", base, candidate],
        capture_output=True, check=False,
    )
    if proc.returncode != 0:
        raise GateError("range-diff-failed")
    parts = proc.stdout.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    paths = []
    index = 0
    while index < len(parts):
        try:
            status = parts[index].decode()
        except UnicodeError as exc:
            raise GateError("range-diff-failed") from exc
        index += 1
        width = 2 if status[:1] in {"R", "C"} else 1
        if index + width > len(parts):
            raise GateError("range-diff-failed")
        for raw in parts[index:index + width]:
            try:
                paths.append(raw.decode())
            except UnicodeError as exc:
                raise GateError("range-diff-failed") from exc
        index += width
    return paths


def _short_rev(value):
    text = str(value).strip()
    if re.fullmatch(r"[0-9a-fA-F]{7,64}", text):
        return text[:12].lower()
    return text[:40]


def schema_not_required(base, candidate):
    """Print the skip line when this range cannot change the schema gate's inputs.

    Returns True when the caller should exit 0 without contacting the database.
    """
    if not paths_require_schema(changed_paths(base, candidate)):
        print(
            "[schema-gate] not-required "
            "reason=no tracked storage/src/storage/entity change and no tracked "
            "migration file "
            f"in {_short_rev(base)}..{_short_rev(candidate)}; "
            "on-disk migration/ is gitignored and not inspected"
        )
        return True
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=None, help="Start of the outgoing range")
    parser.add_argument("--candidate", default=None, help="End of the outgoing range")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("check")
    apply = sub.add_parser("apply")
    apply.add_argument("--file", type=Path, required=True)
    args = parser.parse_args(argv)
    if (args.base is None) != (args.candidate is None):
        print("[schema-gate] env=prod error=range-incomplete", file=sys.stderr)
        return 2
    try:
        if (args.command != "apply" and args.base is not None
                and schema_not_required(args.base, args.candidate)):
            return 0
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
