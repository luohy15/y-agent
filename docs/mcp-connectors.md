# MCP connectors: deployment and operations

Requirements: [MCP Connectors PRD](prd/mcp-connectors.md). Management UI/CLI:
`/Users/roy/luohy15/code/y-module/mcp/README.md`. Host backend contract **v21** is
required by the module. This runbook describes preparation, not evidence that
production OAuth, KMS or a model-driven tool call has succeeded.

The API owns OAuth, encrypted credentials, provider connections and the runtime
gateway. The worker mints an owner/process-scoped grant and stages a fixed stdio
adapter on the VM. The adapter calls the API with that grant, never with provider
credentials. Module publication/rollback does not change host credential state.

## Configuration inventory

Supply these non-secret deployment values through the existing GitHub environment
`CONFIG` JSON or the manual deploy environment. Both deploy paths pass the same SAM
parameters. Do not put provider tokens, static headers or client secrets in either.

| Environment variable | SAM parameter | Consumer / value |
|---|---|---|
| `Y_AGENT_MCP_KMS_KEY_ID` | `McpKmsKeyArn` | API. Existing symmetric `ENCRYPT_DECRYPT` KMS **key ARN**, not an alias. Empty denies encrypted credential/session operations. |
| `Y_AGENT_MCP_CRYPTO_CONTEXT` | `McpCryptoContext` | API. Stable deployment context, default `y-agent`. Keep it unchanged for the lifetime of the stored ciphertext. |
| `Y_AGENT_MCP_OAUTH_REDIRECT_URI` | `McpOAuthRedirectUri` | API. Exact `https://<public-api-host>/api/mcp/oauth/callback`, no query or fragment. Empty disables Connect. |
| `Y_AGENT_MCP_WEB_RETURN_URL` | `McpWebReturnUrl` | API. Optional fixed HTTPS web URL. Leave empty to show the sanitized callback outcome page. No caller-controlled redirect. |
| `Y_AGENT_MCP_GATEWAY_URL` | `McpGatewayUrl` | **Worker**, not just API. Exact `https://<public-api-host>/api/mcp/runtime`, no launch ID, query, fragment or trailing slash. Worker probes and VM adapters must reach it. |
| `Y_AGENT_MODULE_MAINTAINER_USER_ID` | `ModuleMaintainerUserId` | Existing API management gate; the public string user ID also scopes the KMS policy. Verify the SAM value against the configured account before rollout. |

URLs are explicitly configured, not inferred from a request Host header. Prefer
one stable HTTPS CloudFront/custom-domain origin for callback and gateway. If the
approved deployment uses `yovy.app`, the callback is
`https://yovy.app/api/mcp/oauth/callback` and gateway is
`https://yovy.app/api/mcp/runtime`. These examples are not provider registration
or rollout approval. With a CloudFront-generated hostname, configure it explicitly
after the existing distribution is known; there is no template circular reference.

The deploy helpers only forward **nonempty** environment values. Unsetting a value
is not an emergency revocation method and does not reliably clear an existing
stack parameter. Explicit parameter clearing requires a reviewed deployment change
set. Use connector disconnect/stop for access removal.

## KMS and IAM prerequisite

A maintainer separately provisions or identifies a same-region symmetric KMS key.
This template creates **no key** and runs no migration. When `McpKmsKeyArn` is
nonempty, its conditional `McpCredentialKeyPolicy` attaches only
`kms:GenerateDataKey` and `kms:Decrypt` for that exact ARN to `LambdaRoleName`.
Both operations require `kms:EncryptionContext:deployment = McpCryptoContext` and
`kms:EncryptionContext:owner = ModuleMaintainerUserId`. The key policy must permit
that role's use through IAM (or explicitly grant the same constrained operations).
The deployment principal needs permission to manage this inline role policy;
`CAPABILITY_IAM` is already configured. Do not grant `kms:*`, wildcard-key access,
key administration, or these data-key operations to the VM instance role.

**Existing shared role limitation:** API, Worker and Admin currently use the same
execution role. This policy is not an API-only IAM boundary, even though only the
API receives key/context environment values and uses provider credentials in the
normal runtime path. Inventory the role's other inline/managed policies and key
policy: an existing broader grant can defeat this allow statement's restriction.
Do not claim least-privilege role separation without separately splitting roles.
No new VM KMS permission or central provider secret is needed.

The envelope stores a fresh AES-256 data key encrypted by KMS, an AES-GCM nonce,
ciphertext and the KMS key ID. Deployment, public owner ID, connector ID, identity
generation and payload kind are authenticated by KMS and AES-GCM. Launch session
envelopes also bind the launch. Encryption context is visible in KMS audit records;
it must not contain token values. SQL backups alone cannot decrypt credentials.

Confirm API network access to regional KMS, PostgreSQL, DNS and public HTTPS
provider endpoints. VPC Lambdas need an approved outbound route (and/or KMS endpoint)
and security-group rules. The worker and VM need TLS access to the gateway.
Application egress rejects private/loopback/link-local/metadata destinations, pins
DNS results and verifies TLS; do not disable those checks to repair connectivity.

## Gateway, cache and logging

- Exact anonymous exceptions are GET `/api/mcp/oauth/callback` (single-use OAuth
  state) and POST `/api/mcp/runtime/<UUID>` (launch bearer grant). Management stays
  authenticated at `/api/module/mcp/*`; a Lambda Function URL with `AuthType: NONE`
  does not make these application checks optional.
- The first CloudFront behavior `/api/mcp/*` is HTTPS-only, uses AWS managed
  **CachingDisabled** (`4135ea2d-6df8-44a3-9df3-4b5a84be39ad`), and forwards headers,
  cookies and query strings except viewer Host via **AllViewerExceptHostHeader**
  (`b689b0a8-53d0-40ab-baf2-68738e2966ac`). Authorization must reach the gateway;
  state/code/issuer must reach the callback. Do not add redirect/rewrite middleware
  or cache either path. Origin TLS is mandatory. The app sends `Cache-Control:
  no-store`, `Pragma: no-cache`, and `Referrer-Policy: no-referrer`.
- Gateway operation budgets are 10s (ordinary operations) and 30s (`tools/call`).
  The API Lambda timeout is 900s and CloudFront API origin read timeout is 60s,
  both above the gateway budget; the adapter socket timeout is 40s. Keep any added
  proxy timeout above 30s with response overhead headroom. Startup probes have a
  separate 15s selection budget. An `excluded` connector was left out of this
  launch and cannot be revived in place by a late probe result.
- The template deliberately has no CloudFront access logging. Standard access
  logs contain callback query strings. Before enabling any distribution logging,
  real-time logs, WAF logs, reverse-proxy access logs, tracing or request capture,
  arrange exclusion/redaction **before persistence** for callback query strings
  and Authorization/Cookie headers and request/response bodies on MCP paths.
  Do not log provider payloads, consent URLs, state, codes, token responses or
  launch context files. Application Uvicorn filtering strips MCP query strings,
  but cannot sanitize upstream infrastructure logs. Retrofitting redaction after
  data has been logged is not protection.
- Observe only public connector/launch IDs, sanitized outcome/error codes, duration
  and HTTP status. Never paste a callback URL, grant or raw provider failure into
  chats, todo progress, screenshots or deployment diagnostics.

## VM adapter and version rollout

No global MCP registration, `claude mcp add`, pip package or user/project settings
change is needed. The worker's deployed AgentLayer includes
`/Users/roy/luohy15/code/y-agent/agent/src/agent/mcp/adapter.py`; each actual process
launch copies those exact bytes over SFTP with the private config/context. The
worker build/commit is therefore the adapter version. Updating a repository on the
VM alone does **not** upgrade the deployed worker's adapter. Keep API and worker
artifacts from the same reviewed host candidate.

The execution VM needs `python3` on PATH in the noninteractive SSH/tmux environment,
standard-library `ssl` with a working public CA store, and existing SSH/SFTP/tmux
support. Python 3.11+ matches the host's supported floor. Check without starting a
model: `python3 --version`, `python3 -c 'import ssl; ssl.create_default_context()'`,
`claude --version`, and `claude --help`. Require `--strict-mcp-config` and
`--mcp-config` on the installed CLI. The verified development combination was
Claude Code **2.1.284**, with official MCP SDK **2.2.0** used only as a throwaway
protocol-test client (not a runtime dependency). Record deployed versions afresh;
this is not a promise that arbitrary later CLI versions are compatible.

The directory is `/tmp/y-mcp-<chat-hash>-<launch-uuid>` mode 0700; adapter,
`config.json` and per-connector `context-<index>.json` are 0600. Only the private
context contains the launch grant; command arguments contain file paths. Never
inspect or archive those files for support. The same VM OS user can read them;
this is not a sandbox against that user. Normal exit traps, interrupt/stale-relaunch
cleanup and failed staging remove material. Cleanup is scoped to a chat hash, not
all running sessions. After a VM crash, remove only confirmed orphan directories
through an approved cleanup, never a blanket deletion while sessions run.

Fresh/resumed processes use strict host config, falling back to strict empty MCP
config with a sanitized warning if setup fails. Built-ins remain available. Steer
and worker monitor handoff retain the existing launch. Completion/stop revokes the
grant; if the monitor is lost, heartbeat cessation leads to the 30-minute idle
expiry. Disconnect removes reusable central auth but does not promise cancellation
of a provider operation already in flight.

## Ordered rollout checklist (separate authorization required)

1. Freeze repository, target environment/ref, baseline/candidate SHAs and included
   todos, including the separate `mcp` module candidate. Obtain rollout authorization
   and the repository publication slot. Include key/policy configuration, provider
   callback registration, VM prerequisite changes and quota-consuming acceptance
   explicitly. Do not infer permission from PRD approval.
2. Identify the existing KMS key and review its policy, the shared role, network
   paths and log exclusions above. Set the stable callback/gateway values in both
   deployment paths. Authorize any needed resource or policy changes separately.
3. **Manual DDL BEFORE host deploy.** The maintainer reviews and applies
   `/Users/roy/luohy15/code/y-agent/migration/3796_mcp_connectors.sql` to the intended
   database, with the usual backup and schema/catalog verification. It is additive,
   local-only and shared across worktrees, not bundled or automatically run by
   SAM/CI/admin. Record its checksum and maintainer confirmation. Every new
   Claude Code launch touches MCP tables, even with no enabled connectors; deploying
   the host first causes visible connector-load warnings on ordinary chats.
4. Deploy the reviewed host API and worker together, including AgentLayer and SAM
   parameters/policy. Verify worker `Y_AGENT_MCP_GATEWAY_URL`, API key/context and
   callback configuration through non-secret configuration inspection. Check API
   contract v21 before publishing the module. Do not print all Lambda environment
   variables (other features contain secrets).
5. Verify the execution VM prerequisites above. Run deterministic fixture gates
   on the reviewed candidate; fixture traffic is not live provider acceptance.
   Publish the separately reviewed `mcp` module only under its own authorized
   candidate/slot. No connector is enabled automatically by host deployment.
6. **Alpha Vantage prerequisite:** provider registration must allow the exact
   fixed y-agent callback. The audited provider source did not yet include the
   y-agent host in its callback allowlist; DCR does not bypass that restriction.
   Coordinate the minimal exact callback addition in the provider repository
   separately or obtain deployed evidence it is supported. Do not broaden to a
   wildcard domain. Metadata advertising OAuth is not evidence of successful consent.
7. Roy uses Connect, consents in the browser, sees success and discovers tools.
   Approve one deliberately chosen bounded read-only flat tool, then enable.
   Start a fresh Claude Code process and confirm only the approved tool is listed
   and can execute despite bypassPermissions; check a relay-backed bot too. The
   built-in `--tools` selection must not inadvertently hide MCP tools. This actual
   model/quota check is manual and is not covered by the SDK fixture.
8. Keep that process across token expiry, confirm central refresh without policy
   widening, then alter approval/disable and observe the next-launch notice.
   Stop/resend must use the new selection. Verify a failing connector leaves
   healthy connectors/built-ins usable. Separately test write-only static `apikey`
   header mode, replacement/clear/disconnect, not a URL query or CLI argument.
   Static-key success does not satisfy OAuth acceptance. Record only sanitized
   observations, never consent URLs or secret material.

## Recovery, key rotation and rollback

- `not_ready`/Connect unavailable: check fixed callback configuration, key/IAM and
  metadata reachability without capturing payloads. `reconnect_required` needs
  fresh consent. A transient provider failure can be retried explicitly; never
  automatically repeat an uncertain `tools/call`. A launch marked `excluded`
  requires stop/resend after repairing the cause.
- Missing/unavailable KMS or invalid ciphertext denies connector access, not a
  plaintext fallback. Restore key permissions/connectivity and the original
  deployment context. No-auth connectors may still need KMS for encrypted upstream
  session state, so provision the key for the feature rather than assuming no-auth
  means keyless runtime.
- Prefer **KMS automatic rotation on the same key ARN**. KMS retains previous
  backing versions, so old envelopes remain readable without rewriting SQL. Test
  decrypting old and newly written fixture/approved records before declaring a
  rotation successful. Never disable/delete a key while reachable ciphertext or
  backups still depend on it.
- **Replacing the key ARN is a separate migration**, not an alias edit. The envelope
  remembers its original key ID. The SAM policy grants only the configured key, so
  changing that parameter alone removes access to older envelopes. No operator CLI
  rewrap command is shipped. The internal `storage.service.mcp.rewrap_credentials`
  helper re-seals bounded batches of credential rows with read-back verification;
  it does not cover pending OAuth transactions or runtime sessions. Its target ARN
  must match the configured key. A reviewed replacement plan must temporarily retain
  exact old-key Decrypt permission, grant new-key GenerateDataKey/Decrypt with the
  same context restrictions, re-seal credentials and explicitly drain/expire or
  re-seal OAuth transactions and runtime sessions, verify reads, and cover backup
  retention before retiring the old key.
  Do not improvise SQL ciphertext edits or put plaintext into a migration. Loss of
  the old key requires reconnecting/re-entering credentials, not database recovery.
- Changing `McpCryptoContext` or the maintainer owner scope is not key rotation.
  Preserve the original context/owner for old data or explicitly disconnect and
  reauthorize under a reviewed transition. Reassigning the maintainer management
  gate does not itself stop existing owner-scoped runtime grants.
- Disable preserves credentials and affects next launches. For immediate removal
  of reusable auth, disconnect/remove and stop the affected chats; provider-side
  revocation outcome is separate and may fail even though local auth was destroyed.
  Stop/resend is the explicit process boundary; nothing cancels already-executing
  upstream work. Module disable/rollback alone does not revoke credentials/grants.
- Before an authorized host rollback, stop MCP-backed processes and disconnect or
  disable selected connectors as appropriate. Keep the additive schema and KMS key
  intact; older module versions cannot roll back central state. Rolling to a host
  below contract v21 makes this module incompatible. Retain old deployed artifacts
  and key permissions needed for a separately authorized recovery, rather than
  deleting tables or keys as part of rollback.

## Deterministic vs. live evidence

Local-only tests live in the per-package test directories. From the isolated host
worktree, run `uv sync --locked`, `sam validate --lint`,
`bash -n scripts/deploy.sh`, Python compileall and `git diff --check`. S6's
`agent/tests/test_mcp_3796_infra.py` asserts IAM scope, environment routing,
URL validation, CloudFront behavior and both deployment mappings. The existing
`agent/tests/test_mcp_3796_cli_wire.py` drives the exact staged adapter through
stdio and fixture HTTPS using the official SDK; use the disposable PostgreSQL
fixture and `MCP_SDK_PYTHON_3796`, never a production database. Local fixture tests
are not committed under project policy.

These checks do not prove live IAM, provider consent, external log redaction, VM
networking or actual model tool exposure. Keep those as explicit rollout evidence.
