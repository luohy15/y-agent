#!/usr/bin/env python3
"""Explicit one-account migration; never invoked by app startup or deployment.

Requires an approved production run, applied DDL, quiesced writers, configured
master keys, and an available pre-2678 RDS snapshot. No master-key generation here.

Inventory fingerprints use the exact PostgreSQL expressions below. Separately,
read-back canonicalization is UTF-8 JSON of ordered rows containing id, public id
and classified values (sort_keys=True, ensure_ascii=False, separators=(',', ':')).
SHA-256 before/after must match. JSON lexical whitespace is not content; chat
search_text is deliberately cleared and checked separately, not fingerprinted
in the canonical content digest. An inventory mismatch always aborts.

Before commit any failure rolls back every write. After commit, recovery is an
operator-approved restore of the pre-2678 snapshot, never plaintext downgrade.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "storage/src"))

from sqlalchemy import text  # noqa: E402
from storage.crypto.fields import SPECS  # noqa: E402
from storage.crypto.guard import _TABLES  # noqa: E402
from storage.crypto.tenant import (  # noqa: E402
    _insert_key, clear_cache, key_state, master_keys, open_stored, seal,
)
from storage.database.base import get_db  # noqa: E402

USER_ID = 59
EMAIL = "roy.luo@alphavantage.co"
COUNTS = {"chat": 46, "user_preference": 5, "vm_config": 1}
FINGERPRINTS = {
    "chat": ("3fa16b95a899226e28c46f8e8694e7bd", "md5(string_agg(chat_id||':'||md5(coalesce(title,''))||':'||md5(coalesce(json_content,''))||':'||md5(coalesce(search_text,'')), '' order by id))"),
    "user_preference": ("20365be9e6ad4f02b92ccb9246ab8f12", "md5(string_agg(key||':'||md5(value::text), '' order by key))"),
    "vm_config": ("67f2678cbedce673c324189256c71625", "md5(name||':'||md5(coalesce(api_token,''))||':'||md5(coalesce(vm_name,''))||':'||md5(coalesce(work_dir,'')))"),
}
MIGRATED = {spec.table: spec for spec in SPECS.values() if spec.table in COUNTS}


class MigrationRefused(Exception):
    """Only fixed, non-secret invariant codes may be reported."""


def require(ok: bool, code: str) -> None:
    if not ok:
        raise MigrationRefused(code)


def scalar(session, sql, **params):
    return session.execute(text(sql), params).scalar_one()


def owner_source(table):
    if table == "mcp_credential":
        return 'mcp_credential t JOIN mcp_connector c ON c.id=t.connector_pk', 'c.user_id'
    return f'"{table}" t', 't.user_id'


def canonical(rows) -> str:
    data = json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def content(session, *, encrypted: bool) -> dict:
    result = {}
    for table, spec in MIGRATED.items():
        columns = ("id", spec.public_attr, *spec.fields)
        selection = ', '.join(f'"{name}"' for name in columns)
        rows = session.execute(text(f'SELECT {selection} FROM "{table}" WHERE user_id=:uid ORDER BY id'), {"uid": USER_ID}).mappings()
        values = []
        for row in rows:
            row = dict(row)
            if encrypted:
                for column in spec.fields:
                    if row[column] is not None:
                        row[column] = open_stored(session, user_id=USER_ID, table=table, column=column,
                                                  public_id=str(row[spec.public_attr]), value=row[column])
            values.append(row)
        result[table] = values
    return result


def inventory(session) -> dict:
    require(scalar(session, "SELECT current_database()") == "yovy", "database_mismatch")
    require(scalar(session, 'SELECT count(*) FROM "user"') == 124, "user_count_mismatch")
    require(scalar(session, 'SELECT email FROM "user" WHERE id=:uid', uid=USER_ID) == EMAIL, "account_mismatch")
    require(scalar(session, 'SELECT count(*) FROM "user" WHERE encryption_eligible') == 0, "eligible_mismatch")
    require(scalar(session, 'SELECT count(*) FROM tenant_key') == 0, "keys_already_exist")
    others = {}
    for table in _TABLES:
        require(scalar(session, f'SELECT count(*) FROM "{table}" WHERE enc_version<>0') == 0, "encrypted_inventory_mismatch")
        source, owner = owner_source(table)
        count = scalar(session, f'SELECT count(*) FROM {source} WHERE {owner}=:uid', uid=USER_ID)
        require(count == COUNTS.get(table, 0), f"count_mismatch:{table}")
        others[table] = scalar(session, f'SELECT count(*) FROM {source} WHERE {owner} IS DISTINCT FROM :uid', uid=USER_ID)
    for table, (expected, expression) in FINGERPRINTS.items():
        actual = scalar(session, f'SELECT {expression} FROM "{table}" WHERE user_id=:uid', uid=USER_ID)
        require(actual == expected, f"fingerprint_mismatch:{table}")
    require(scalar(session, 'SELECT sum(octet_length(json_content)) FROM chat WHERE user_id=:uid', uid=USER_ID) == 1_973_688,
            "chat_bytes_mismatch")
    # Module tables are not rewritten. Refuse new target-owned module/blob data
    # in the audited families so the zero-blob premise cannot silently drift.
    tables = session.execute(text("SELECT table_name FROM information_schema.columns WHERE table_schema='public' AND column_name='user_id'")).scalars()
    for table in tables:
        if table.startswith(("photo", "voice", "im_", "vault", "finance", "food")):
            require(table.replace('_', '').isalnum(), "invalid_inventory_table")
            require(scalar(session, f'SELECT count(*) FROM "{table}" WHERE user_id=:uid', uid=USER_ID) == 0,
                    f"module_data_present:{table}")
    return others


def verify(session, expected: dict, others: dict) -> None:
    require(scalar(session, 'SELECT count(*) FROM "user"') == 124, "user_count_changed")
    require(session.execute(text('SELECT id FROM "user" WHERE encryption_eligible')).scalars().all() == [USER_ID], "eligibility_mismatch")
    require(scalar(session, "SELECT count(*) FROM tenant_key") == 1, "key_count_mismatch")
    require(scalar(session, "SELECT count(*) FROM tenant_key WHERE user_id=:uid AND status='active'", uid=USER_ID) == 1, "active_key_mismatch")
    for table in _TABLES:
        source, owner = owner_source(table)
        require(scalar(session, f'SELECT count(*) FROM {source} WHERE {owner} IS DISTINCT FROM :uid', uid=USER_ID) == others[table],
                f"other_count_changed:{table}")
        require(scalar(session, f'SELECT count(*) FROM {source} WHERE {owner} IS DISTINCT FROM :uid AND t.enc_version<>0', uid=USER_ID) == 0,
                f"other_encryption_changed:{table}")
        require(scalar(session, f'SELECT count(*) FROM {source} WHERE {owner}=:uid AND t.enc_version=1', uid=USER_ID) == COUNTS.get(table, 0),
                f"sealed_count_mismatch:{table}")
        require(scalar(session, f'SELECT count(*) FROM {source} WHERE {owner}=:uid AND t.enc_version<>1', uid=USER_ID) == 0,
                f"plaintext_remaining:{table}")
    require(scalar(session, 'SELECT count(*) FROM chat WHERE user_id=:uid AND search_text IS NOT NULL', uid=USER_ID) == 0, "search_index_not_cleared")
    require(canonical(content(session, encrypted=True)) == canonical(expected), "readback_mismatch")


def migrate(snapshot_id: str) -> None:
    import boto3
    require(snapshot_id.startswith("pre-2678-"), "snapshot_name_mismatch")
    snapshot = boto3.client("rds", region_name="us-east-1").describe_db_snapshots(DBSnapshotIdentifier=snapshot_id)["DBSnapshots"][0]
    require(snapshot["Status"] == "available" and snapshot["DBInstanceIdentifier"] == "alphavantage-news-infra-postgres", "snapshot_unavailable")
    current, keys = master_keys()
    require(bool(current and keys), "master_key_unconfigured")
    clear_cache()
    with get_db() as session:
        session.execute(text("SET LOCAL lock_timeout = '10s'"))
        session.execute(text("SET LOCAL statement_timeout = '120s'"))
        session.execute(text("SELECT pg_advisory_xact_lock(2678, 59)"))
        # Cooperating migration lock plus actual table locks exclude concurrent
        # writers that do not participate in the advisory-lock protocol.
        for table in sorted((*_TABLES, "user", "tenant_key")):
            session.execute(text(f'LOCK TABLE "{table}" IN SHARE ROW EXCLUSIVE MODE'))
        others = inventory(session)
        before = content(session, encrypted=False)
        _insert_key(session, USER_ID, "active")
        session.flush()
        material = key_state(session, USER_ID).active
        require(material is not None, "active_key_missing")
        for table, spec in MIGRATED.items():
            while True:
                rows = session.execute(text(f'SELECT * FROM "{table}" WHERE user_id=:uid AND enc_version=0 ORDER BY id LIMIT 100'), {"uid": USER_ID}).mappings().all()
                if not rows:
                    break
                for row in rows:
                    params = {"uid": USER_ID, "id": row["id"]}
                    assignments = ["enc_version=1"]
                    for column in spec.fields:
                        value = row[column]
                        if value is not None:
                            value = seal(material.dek, user_id=USER_ID, table=table, column=column,
                                         public_id=str(row[spec.public_attr]), value=value, key_id=material.key_id)
                        # user_preference.value is JSON, containing the envelope string.
                        params[column] = json.dumps(value) if table == "user_preference" else value
                        assignments.append(f'"{column}"=CAST(:{column} AS json)' if table == "user_preference" else f'"{column}"=:{column}')
                    assignments.extend(f'"{column}"=NULL' for column in spec.clear)
                    session.execute(text(f'UPDATE "{table}" SET {", ".join(assignments)} WHERE id=:id AND user_id=:uid AND enc_version=0'), params)
        session.execute(text('UPDATE "user" SET encryption_eligible=true WHERE id=:uid'), {"uid": USER_ID})
        verify(session, before, others)
    # Fresh connection/transaction after commit; failure here requires snapshot
    # recovery, never an attempted partial inverse migration.
    print("Migration transaction committed; starting fresh-transaction verification.")
    clear_cache()
    with get_db() as session:
        verify(session, before, others)
    print("Migration verified: 52 sealed rows, one active key, eligible only user 59.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-account", required=True, choices=[EMAIL])
    parser.add_argument("--snapshot-id", required=True)
    args = parser.parse_args()
    try:
        migrate(args.snapshot_id)
    except MigrationRefused as exc:
        print(f"Migration refused: {exc}. If already committed, snapshot recovery is required.", file=sys.stderr)
        return 1
    except Exception:
        # Exception repr may contain SQL parameters. Never log it.
        print("Migration failed. If commit occurred, use the approved snapshot recovery procedure; do not retry blindly.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
