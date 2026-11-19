---
title: Hosted tenant confidentiality (L1)
type: prd
project: y-agent
feature: second-user-confidentiality
status: active
---

# Hosted tenant confidentiality (L1)

Authoritative requirements for protecting enabled tenants' classified content
from ordinary Postgres dump/backup and S3 access without the server-held key.
Assessment: `pages/plan-2678-wu-confidentiality.md`. Acceptance and rollout:
`pages/plan-2678-encryption-design.md` and `pages/plan-2678-activation-rollout.md`.

## Boundary

The sole named existing-account migration exception is internal user 59,
`roy.luo@alphavantage.co`: 46 chats, 5 preferences and 1 VM configuration.
The separately approved migration may set eligibility and seal those 52 rows.
Every other existing account, including operator `luohycs@gmail.com` (85),
remains plaintext (`enc_version=0`), ineligible and without tenant keys.
The API enable operation stays refused for every account. Future tenant
activation remains gated by todo 4371 owner-scoped reads and the rollout's
remaining acceptance checks. This code does not activate a node or provider,
copy operator credentials, or prove the tenant's `prod` node is usable.

Module-owned tables (including IM, finance, food and vault) are outside L1 v1.
Photos and upload object bodies are also outside L1: presigned access and
infrastructure SSE-S3 do not provide application-layer confidentiality.
Photos and voice remain restricted to the configured maintainer. There are
no audited target photo/upload/voice rows to migrate. Voice originals and
voice part uploads use application envelopes when their owner is encryption-active;
part identities are authenticated independently before final assembly.

## Guarantee

- Classified encrypted content is unreadable from database/S3 copies alone.
  IDs, metadata, enums, timestamps, counters and blind-index equality remain
  visible. Legacy global links remain shared and plaintext; enabled-tenant
  links are per-user and do not reuse other tenants' content.
- This is server-managed encryption, not E2EE or an operator-proof boundary.
  Anyone with the master key, Lambda environment, process memory, execution
  node, relay, provider access or the ability to replace running code can
  obtain plaintext. Infrastructure encryption alone does not satisfy L1.
- Pre-migration plaintext remains in seven-day backups, snapshots and existing
  logs until their retention expires. New application encryption cannot erase
  those copies. Log retention is a separate operational change (30 days).

## Keys and envelope

A self-managed 32-byte AES-256-GCM master key wraps a per-tenant 32-byte DEK
and separate blind-index key. No KMS/CMK, KMS IAM policy or paid key service
is required. `tenant_key` holds ciphertext plus tag in `wrapped_dek` and
`bidx_wrapped`, 12-byte nonces in `wrap_nonce` and `bidx_nonce`, and
`master_key_id`. The retained legacy `kms_key_arn` column stays empty.
Wrap AAD: `y-agent/kek/v1:<internal user id>:<purpose>:<tenant key id>`;
`purpose` distinguishes `dek` from `bidx`.

API, worker and admin use `Y_AGENT_TENANT_MASTER_KEYS` (JSON map of id to
base64url 32-byte key) and `Y_AGENT_TENANT_MASTER_KEY_ID` (current wrapping id).
Missing/unknown keys, malformed configuration and failed authentication are
closed errors. A missing key row never makes an encrypted value plaintext.
Only unwrapped material is cached (bounded, ten minutes); every encrypted
read re-queries the key row, including its current wrapped bytes and status,
before cache reuse. No positive or negative tenant-state cache exists.
A committed shred or rewrap reaches other processes on their next read under
normal READ COMMITTED transactions; already-returned plaintext is not revoked.

Content: `yenc:v1:<key_id>:<b64url nonce>:<b64url ciphertext||tag>`, AES-256-GCM.
AAD: `y-agent/v1:<internal user id>:<table>:<column>:<public row id>:1`.
`enc_version=0` means legacy plaintext; `1` means each classified value is an
envelope or null. Invalid version-1 content fails closed. Voice metadata
`yenc=1` selects decryption even after disable/shred, with stored-size bounds;
part AAD uses `voice`, `part:<six-digit index>`, and the take id.

Exact filters use `base64url(HMAC-SHA256(k_bidx, "<purpose>\0<nfc value>"))`.
Enabled-tenant free text has no server index (exact public-id lookup only);
tag prefix search becomes exact. RSS alias rewrites remain owner-scoped and
set-based classified writes are refused.

## Custody, rotation and recovery

The canonical private file is `~/.y-agent/secrets/tenant-master-key`, owned by
the deployment user, mode 0600, outside the checkout. Its JSON format is
`{"current":"<id>","keys":{"<id>":"<base64url-32-bytes>"}}`.
Keep one off-machine recovery copy outside database backups, with a SHA-256
fingerprint checked over the exact file bytes. Never put key material in git,
shell history, logs, CI output or database rows. Key creation and custody
placement require the named rollout authorization; the repository generates
no master key. Losing every copy makes encrypted data unrecoverable.

SAM `TenantMasterKeys` is NoEcho. `scripts/tenant_deploy.py` loads and validates
private-file or environment configuration and redacts SAM output; it does not
access the database. GitHub-hosted runners have no route to the private RDS,
so CI runs only this wrapper, with protected environment secrets and masking
of each key value. It never writes keys to artifacts or saved SAM configuration.

The fail-closed database gate runs on the DB-reachable deploy/release host:
`uv run python scripts/tenant_encryption_guard.py`. It loads the same private
key file (or supplied environment) before checking schema and all referenced
master IDs. `scripts/deploy.sh` runs it before invoking the SAM wrapper and
stops on failure. For a CI deployment, the publisher must run it on that host
before pushing the candidate, using the same key map/current ID that CI will
deploy, and record candidate-bound evidence. CI does not enforce this host-side
prerequisite or prove key-map parity; both are publication gates. An unavailable
database still fails the host gate closed. Runtime Lambda environments
necessarily hold the key map and are within the trusted boundary.

To rotate, deploy the old and new IDs together with the new current ID,
rewrap both DEK and blind-index keys, then verify all live `master_key_id`
references before removing the old ID. Content envelopes do not change.
Keep historical KEKs in protected recovery custody for backups that still
reference them. Removing a referenced ID fails closed, including warm caches.
A recovery drill restores the private file from the independent copy, checks
its fingerprint and unwraps a row in a protected process without printing
keys or plaintext. Restoring a database requires its matching historical KEKs.

## Lifecycle and migration

- DEK rotation retires the old row and creates an active key. Old content
  remains readable through its envelope key id.
- Disable returns new writes to plaintext but still decrypts old content.
- Shred deletes live tenant key rows and clears this process's cache. Other
  processes check row existence on their next encrypted read. The operator
  cannot be shredded here. Snapshots containing wrapped DEKs remain readable
  while the shared KEK exists; copied DEKs/plaintext also survive. Shred is
  not immediate erasure, nor does shared-KEK destruction isolate one tenant.
- `scripts/2678_tenant_encryption.sql` adds schema only, including the additive
  `master_key_id` column for existing installations; it never backfills.
- `scripts/migrate_tenant_2678.py` is an explicit, separately approved command,
  never a startup/deploy hook. It requires an available `pre-2678-*` snapshot,
  exact account confirmation, configured keys and quiesced production writers.
  One transaction takes `pg_advisory_xact_lock(2678, 59)` plus table locks,
  verifies inventory/fingerprints, inserts one active key, seals only the
  three named tables, sets user 59 eligible, checks zero remaining plaintext
  and read-back equality, and commits. A fresh transaction verifies again.
  Any inventory mismatch aborts; no automatic baseline refresh is allowed.
- The script documents the exact inventory SQL and canonical JSON content
  serialization. `chat.search_text` is deliberately cleared, so content
  equality excludes it and separately requires null. Typed preference JSON
  equality ignores lexical whitespace. Inventory fingerprints still match
  the original PostgreSQL serialization before any write.
- Before commit, failure rolls back the entire migration. After commit,
  recovery requires the approved snapshot restore; no inverse plaintext
  migration or rollback to a reader lacking version-1 support is permitted.
  Deploy guards refuse unread databases, missing schema/key rows, or
  unconfigured referenced master IDs. Snapshot/retention changes and live
  schema/data verification remain separate rollout gates.
