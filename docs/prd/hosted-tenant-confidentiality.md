---
title: Hosted tenant confidentiality (L1)
type: prd
project: y-agent
feature: second-user-confidentiality
status: active
---

# Hosted tenant confidentiality (L1)

Authoritative requirements for hosting a non-operator user so that ordinary
operator access to Postgres, its backups, and S3 does not reveal that user's
content. Assessment history: `pages/plan-2678-wu-confidentiality.md`. Checks:
`pages/plan-2678-encryption-design.md`.

## Boundary (todo 2678)

Existing accounts, including the operator (`luohycs@gmail.com`), are never
encryption-enabled and are not backfilled. Their rows stay `enc_version=0`
plaintext and their reads stay unchanged. Encryption applies only to a future
hosted tenant that is explicitly marked eligible. This delivery does not set
that flag, does not insert `tenant_key`, and does not enable any tenant.
Todo 4371 (owner-scoped reads) remains a hard gate before any later enablement.

## Settled defaults

- Module-owned tables (IM, finance, food, and the rest) stay outside L1 v1 and
  must be disclosed as plaintext.
- Photos stay on presigned URLs and use SSE-KMS with a human-deny key policy
  only when `Y_AGENT_PHOTO_KMS_KEY_ARN` is set. Unset keeps today's SSE-S3.
- Deletion is crypto-shred: remove `tenant_key` (and the user row, which
  cascades). Live ciphertext becomes unreadable. Snapshots and noncurrent S3
  versions remain readable with the CMK until backup retention expires.
  Per-tenant KMS keys are not v1.
- Link rows for an enabled tenant are per-user. Cross-tenant URL dedup is
  dropped for those rows. Legacy global links stay shared and plaintext.
- RSS alias rewrites affect only the caller’s activities; set-based updates to
  classified fields, blind indexes, cleared columns, or `enc_version` are rejected.

## Guarantee

- L1 protects against SQL dumps, snapshots, replicas, S3 reads, noncurrent
  versions, and log greps, for enabled tenants only.
- L1 does not protect against the account owner changing the key policy, code
  running as the Lambda role, process memory, the execution node, the relay,
  or the model provider.
- Infrastructure SSE does not satisfy L1 for the database. E2EE is not provided.

## Keys and envelope

One `us-east-1` CMK wraps a per-tenant 32-byte DEK and a separate blind-index
key. `tenant_key.status` is `active`, `retired`, or `disabled`. KMS context
uses the internal user id. The process cache holds DEKs for 10 minutes and is
not logged.

Value: `yenc:v1:<key_id>:<b64url nonce>:<b64url ciphertext||tag>`, AES-256-GCM.
AAD: `y-agent/v1:<internal user id>:<table>:<column>:<public row id>:1`.
`enc_version` 0 is legacy plaintext. `enc_version` 1 means every classified
value in the row is an envelope or null. Readers dispatch on `enc_version`.
A version-1 value that is not a valid envelope is a closed error.

Exact filters use `base64url(HMAC-SHA256(k_bidx, "<purpose>\0<nfc value>"))`.
Free text has no server index. Enabled tenants' text search degrades to an
exact public id; tag prefix search degrades to exact.

## Lifecycle

- Enable inserts `tenant_key` only for an eligible non-legacy user, then new
  writes use `enc_version=1`. This build refuses enable.
- Disable (`status=disabled`) returns writes to plaintext and still decrypts
  old rows.
- DEK rotation inserts a new active key and retires the old one. Readers use
  the envelope `key_id`.
- KEK rotation rewraps `wrapped_dek` and does not rewrite rows.
- Crypto-shred deletes `tenant_key` and this process's DEK cache. The operator
  account cannot be shredded or enabled here. Ciphertext, a copied DEK, and
  database snapshots still decrypt until those copies are gone. Shred is not
  immediate erasure.
- Rollback of a build that cannot read `enc_version=1` is refused once any
  such row exists (`scripts/tenant_encryption_guard.py`).

## Deploy

`scripts/2678_tenant_encryption.sql` is additive and unapplied. Apply it
before deploying this build. `migration/` is a gitignored symlink, so the
candidate keeps the DDL in `scripts/`. No tenant is enabled by the script.
`Y_AGENT_TENANT_KMS_KEY_ARN` empty means no wrap key is configured.
