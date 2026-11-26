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
Photos remain restricted to the configured maintainer. Voice objects are open
to every admitted owner (todo 4484) but stay outside L1: `voice_take` is a
module entity, so the transcript columns are not in this registry, while voice
originals and voice part uploads use application envelopes when their owner is
encryption-active; part identities are authenticated independently before final
assembly. There are no audited target photo/upload rows to migrate.

Homepage admission is a separate concern owned by
[public-homepage-admission](public-homepage-admission.md): it decides who may
sign in and call the API, does not change encryption eligibility or tenant
activation, and preserves the same named accounts through an explicit
inventory-first rollout.

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
and separate blind-index key. No customer-managed KMS key or paid key service
is created. `tenant_key` holds ciphertext plus tag in `wrapped_dek` and
`bidx_wrapped`, 12-byte nonces in `wrap_nonce` and `bidx_nonce`, and
`master_key_id`. The retained legacy `kms_key_arn` column stays empty.
Wrap AAD: `y-agent/kek/v1:<internal user id>:<purpose>:<tenant key id>`;
`purpose` distinguishes `dek` from `bidx`.

Runtime resolution order is environment, then the private file, then an
explicitly targeted SSM parameter. `Y_AGENT_TENANT_MASTER_KEYS` and
`Y_AGENT_TENANT_MASTER_KEY_ID` are an optional local override, not Lambda
environment parameters. If either variable is present, an invalid value fails
closed and does not fall through. The private file is next, with the same
fail-closed rule. SSM is used only when `Y_AGENT_TENANT_MASTER_KEY_PARAMETER`
names a parameter. Empty means untargeted and dormant: the process does not
call SSM. The production name is `/y-agent/tenant/master-key`, a standard-tier
SecureString whose JSON body is `{"current":"<id>","keys":{"<id>":"<base64url-32-bytes>"}}`.
A missing targeted parameter leaves encryption dormant. A successful file or
SSM read is cached
in-process for 300 seconds; absence and errors are not cached. Missing/unknown
keys, malformed configuration and failed authentication are closed errors.
A missing key row never makes an encrypted value plaintext.
Only unwrapped DEK material is cached (bounded, ten minutes); every encrypted
read re-queries the key row, including its current wrapped bytes and status,
before DEK-cache reuse. No positive or negative tenant-state cache exists.
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

No tenant key material or GitHub secret is passed to SAM or CI. The template
parameter `TenantMasterKeyParameter` defaults empty, and CI does not override
it, so a candidate deploy leaves every new runtime untargeted. Test and test1
stacks are not given the production name. `scripts/tenant_deploy.py deploy`
validates a present private file or environment override, redacts any loaded
key material, and does not read or write SSM.

`sync-ssm` writes only `/y-agent/tenant/master-key`, and only with
`--confirm-ssm-copy --target production` from a stack other than
`y-agent-test` or `y-agent-test1`. It refuses to drop an existing key id or
replace the bytes of an existing id. It is not part of deploy.

The shared-role grant has one owner, `scripts/tenant_master_key_grant.sh`.
Deploy, `create-role.sh`, and CI do not apply it, and a stack rollback cannot
remove it. The script refuses without `--confirm-role-grant`. It allows
`ssm:GetParameter` on the production parameter and `kms:Decrypt` on the
existing us-east-1 `alias/aws/ssm` key when `kms:ViaService` is SSM and the
encryption context is that parameter. The role is used by all nine prod, test,
and test1 functions. Targeting prevents accidental resolution; it does not
isolate those functions after the grant exists. The AWS-managed key policy
still grants `kms:Decrypt` broadly in the account. A customer-managed key is
out of scope. CI's `GitHubDeployRole` cannot `iam:PutRolePolicy`; that
permission stays absent so the deploy route does not depend on a new IAM grant.

The fail-closed database gate runs on the DB-reachable deploy/release host:
`uv run python scripts/tenant_encryption_guard.py`. It rejects invalid
environment or file configuration before opening the database or falling
through. While the parameter name is empty, the guard does not read SSM, so
deploy stays available before the separate copy and grant. When the name is
set, the private file and that parameter must match, and a present environment
override must match them too. The guard then checks schema and referenced
master IDs. `scripts/deploy.sh` runs it before the SAM wrapper and stops on
failure. CI does not run the guard. An unavailable database, or an SSM read
after targeting, still fails the host gate closed. Lambda does not receive
the key map in its environment.

The maintainer status payload reports `master_key_configured` and
`master_key_id` only. It never returns key bytes. Invalid configuration is a
closed error, not `master_key_configured: false`.

To rotate, put the old and new IDs in the private file and the SSM
parameter together, with the new current ID, rewrap both DEK and blind-index
keys, then verify all live `master_key_id` references before removing the old
ID. Content envelopes do not change. A warm process can keep a successful
master-key read for up to 300 seconds, so rotation is not visible to that
process until the cache expires or the process is replaced. Keep historical
KEKs in protected recovery custody for backups that still reference them.
Removing a referenced ID fails closed, including warm caches.
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
  Missing `DATABASE_URL` and `DATABASE_URL_DEV` refuses with
  `database_unconfigured` and does not connect. `--preflight-only` rechecks the
  inventory in a read-only transaction, takes no migration locks, and does not
  require a master key. The write path loads keys through `master_keys()`.
  One transaction takes `pg_advisory_xact_lock(2678, 59)` plus table locks,
  verifies inventory/fingerprints, inserts one active key, seals only the
  three named tables, sets user 59 eligible, checks zero remaining plaintext
  and read-back equality over all 52 rows, and commits. A fresh transaction
  verifies again. Any inventory mismatch aborts; no automatic baseline refresh
  is allowed.
- Chat and VM fingerprints stay stored-text aggregates. The canonical fingerprint
  for preferences pins `md5(value::jsonb::text)` for `activityBarOrder`, `fileWorkspace`,
  `themePrefs` and `usage_limits_latest`, requires that exact key set plus
  `chat_model_activity_watermark`, and aggregates only the four non-volatile
  keys. The watermark is not part of the drift fingerprint; its value must be
  a one-field object `{"updated_at_unix": <integer>}`. The script documents the
  canonical JSON content serialization. `chat.search_text` is deliberately
  cleared, so content equality excludes it and separately requires null.
  Typed preference JSON equality ignores lexical whitespace.
- Quiescence is an execution gate, not a deploy side effect. Before the
  migration transaction, disable the 14 production `y-agent-*` EventBridge
  rules, excluding `y-agent-test*` and `y-agent-test1*`, after recording each
  rule's prior state. Restore those exact states afterward; do not force a
  rule on just because the migration finished. Drain in-flight invocations.
  Require no running chat or wakeup for user 59, no application session
  writing the target tables, and an operator checkpoint that account 59 is
  idle. `RefreshUsageLimits` does not own user 59's usage row. `SyncModelUsage`
  is the scheduled writer of that account's target tables. The migration's
  `SHARE ROW EXCLUSIVE` locks and 10-second `lock_timeout` remain the hard
  guard. There is no positive tenant-state cache, so a delayed ORM write
  re-reads key state and seals.
- Before commit, failure rolls back the entire migration. After commit,
  recovery requires the approved snapshot restore; no inverse plaintext
  migration or rollback to a reader lacking version-1 support is permitted.
  Deploy guards refuse unread databases, missing schema/key rows, or
  unconfigured referenced master IDs. Snapshot/retention changes and live
  schema/data verification remain separate rollout gates.
