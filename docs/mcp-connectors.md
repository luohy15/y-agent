# MCP connectors: deployment and operations

Requirements: [MCP Connectors PRD](prd/mcp-connectors.md). Management UI/CLI:
`/Users/roy/luohy15/code/y-module/mcp/README.md`. Host backend contract **v22** is
required by the module. This runbook describes preparation, not evidence that
production OAuth or a model-driven tool call has succeeded.

The API owns OAuth, central credentials, provider connections and the runtime
gateway. The worker mints an owner/process-scoped grant and stages a fixed stdio
adapter on the VM. The adapter calls the API with that grant, never with provider
credentials. Module publication/rollback does not change host credential state.

## Configuration inventory

Supply these non-secret deployment values through the existing GitHub environment
`CONFIG` JSON or the manual deploy environment. Both deploy paths pass the same SAM
parameters. Do not put provider tokens, static headers or client secrets in either.

| Environment variable | SAM parameter | Consumer / value |
|---|---|---|
| `Y_AGENT_MCP_GATEWAY_URL` | `McpGatewayUrl` | **Worker**, not just API. Exact `https://<public-api-host>/api/mcp/runtime`, no launch ID, query, fragment or trailing slash. Worker probes and VM adapters must reach it. Template default: `https://yovy.app/api/mcp/runtime` (confirmed 2026-10-01). |
| `Y_AGENT_MODULE_MAINTAINER_USER_ID` | `ModuleMaintainerUserId` | API **and Worker**. Existing API management gate; the worker re-checks it at every launch, so connectors of an owner who is not the configured maintainer are skipped (`maintainer_required`). Verify the SAM value against the configured account before rollout. |

URLs are explicitly configured, not inferred from a request Host header. With a
CloudFront-generated hostname, override the gateway explicitly after the existing
distribution is known; there is no template circular reference.

The deploy helpers only forward **nonempty** environment values. Unsetting a value
is not an emergency revocation method and does not reliably clear an existing
stack parameter. Explicit parameter clearing requires a reviewed deployment change
set. Use connector disconnect/stop for access removal.

## OAuth redirect: CLI loopback (RFC 8252)

There is no API-hosted callback and no callback configuration. `y mcp connect <id>`
binds a one-shot listener on `http://127.0.0.1:<port>/callback` (ephemeral port),
asks the host to start the transaction with that exact redirect URI, opens the
browser (printing the URL as a fallback), receives the redirect, and submits
`state` / `code` / `error` / `iss` to the JWT-authenticated module route. The host
consumes the single-use state bound to owner, connector, transaction and redirect
URI, keeps the PKCE verifier, and exchanges the code centrally. The browser that
consents must run on the same machine as the CLI. The web UI does not complete
Connect; it shows `run y mcp connect <id>`.

- Dynamic client registration registers the exact loopback URI per transaction
  (`application_type: native`), so any ephemeral port works.
- A **manually registered OAuth client** must have a loopback redirect
  registered at the provider, and the provider must accept any port for it
  (RFC 8252 section 7.3). A provider that pins one exact port cannot be used.

## Credential storage

Credentials (static header values, OAuth client secrets, access/refresh tokens),
the in-flight OAuth transaction's PKCE verifier and runtime upstream session state
are stored as **plaintext** JSON in PostgreSQL (Roy, 2026-10-01: no encryption at
rest, no KMS). Database access and backups therefore expose them: treat the
database, its snapshots and `psql` sessions as secret-bearing. Kept protections:
every management read is write-only (no API, CLI or UI surface returns a secret),
logs and error payloads are redacted, rows are owner-bound, and the launch grant
is stored only as a digest. The envelope-era `key_id` / `encrypted_data_key` /
`nonce` columns are unused and written as empty strings; the plaintext lives in
the existing `ciphertext` column, so there is no schema change. A stored value
that is not a JSON object answers `reconnect_required`.

Confirm API network access to PostgreSQL, DNS and public HTTPS provider endpoints.
VPC Lambdas need an approved outbound route and security-group rules. The worker
and VM need TLS access to the gateway. Application egress rejects
private/loopback/link-local/metadata destinations, pins DNS results and verifies
TLS; do not disable those checks to repair connectivity.

## Gateway, cache and logging

- The only JWT-exempt MCP route is POST `/api/mcp/runtime/<UUID>` (launch bearer
  grant). Management and OAuth completion stay authenticated at
  `/api/module/mcp/*`; a Lambda Function URL with `AuthType: NONE` does not make
  these application checks optional.
- The first CloudFront behavior `/api/mcp/*` is HTTPS-only, uses AWS managed
  **CachingDisabled** (`4135ea2d-6df8-44a3-9df3-4b5a84be39ad`), and forwards headers,
  cookies and query strings except viewer Host via **AllViewerExceptHostHeader**
  (`b689b0a8-53d0-40ab-baf2-68738e2966ac`). Authorization must reach the gateway.
  Do not add redirect/rewrite middleware or cache the path. Origin TLS is mandatory. The app sends `Cache-Control:
  no-store`, `Pragma: no-cache`, and `Referrer-Policy: no-referrer`.
- Gateway operation budgets are 10s (ordinary operations) and 30s (`tools/call`).
  The API Lambda timeout is 900s and CloudFront API origin read timeout is 60s,
  both above the gateway budget; the adapter socket timeout is 40s. Keep any added
  proxy timeout above 30s with response overhead headroom. Startup probes have a
  separate 15s selection budget. An `excluded` connector was left out of this
  launch and cannot be revived in place by a late probe result.
- The template deliberately has no CloudFront access logging. Before enabling any
  distribution logging, real-time logs, WAF logs, reverse-proxy access logs,
  tracing or request capture, arrange exclusion/redaction **before persistence**
  for Authorization/Cookie headers and request/response bodies on MCP paths
  (the module's OAuth completion body carries a one-time code and state).
  Do not log provider payloads, consent URLs, state, codes, token responses or
  launch context files. Application Uvicorn filtering strips MCP query strings,
  but cannot sanitize upstream infrastructure logs. Retrofitting redaction after
  data has been logged is not protection.
- Observe only public connector/launch IDs, sanitized outcome/error codes, duration
  and HTTP status. Never paste a consent or loopback redirect URL, grant or raw
  provider failure into chats, todo progress, screenshots or deployment diagnostics.

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
   and the repository publication slot. Include provider redirect acceptance, VM
   prerequisite changes and quota-consuming acceptance explicitly. Do not infer permission from PRD approval.
2. Review network paths and log exclusions above. Confirm the gateway value
   (template default `https://yovy.app/api/mcp/runtime`) or override it in both
   deployment paths. Authorize any needed resource changes separately.
3. **Manual DDL BEFORE host deploy.** The maintainer reviews and applies
   `/Users/roy/luohy15/code/y-agent/migration/3796_mcp_connectors.sql` to the intended
   database, with the usual backup and schema/catalog verification. It is additive,
   local-only and shared across worktrees, not bundled or automatically run by
   SAM/CI/admin. Record its checksum and maintainer confirmation. Every new
   Claude Code launch touches MCP tables, even with no enabled connectors; deploying
   the host first causes visible connector-load warnings on ordinary chats. Round 2
   (loopback OAuth, plaintext custody) needs no further DDL.
4. Deploy the reviewed host API and worker together, including AgentLayer and SAM
   parameters. Verify worker `Y_AGENT_MCP_GATEWAY_URL` and
   `Y_AGENT_MODULE_MAINTAINER_USER_ID` through non-secret configuration inspection.
   Check API contract v22 before publishing the module; a v21 module's Connect
   fails on a v22 host, so publish the v22 module right after the host. Do not
   print all Lambda environment variables (other features contain secrets).
5. Verify the execution VM prerequisites above. Run deterministic fixture gates
   on the reviewed candidate; fixture traffic is not live provider acceptance.
   Publish the separately reviewed `mcp` module only under its own authorized
   candidate/slot. No connector is enabled automatically by host deployment.
6. **Alpha Vantage prerequisite:** the provider must accept the loopback redirect
   `http://127.0.0.1:<port>/callback` with an arbitrary port for the registered
   (DCR or manual) client. Confirm this from provider source or deployed evidence
   before live acceptance; do not ask for a wildcard domain. Metadata advertising
   OAuth is not evidence of successful consent.
7. Roy runs `y mcp connect <id>` on a machine with a browser, consents, sees
   success and discovers tools.
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

## Recovery and rollback

- `not_ready`/Connect unavailable: check metadata reachability without capturing
  payloads, and that the CLI listener's port is reachable from the local browser.
  `reconnect_required` needs fresh consent (also the answer for an unreadable
  stored credential). A transient provider failure can be retried explicitly;
  never automatically repeat an uncertain `tools/call`. A launch marked `excluded`
  requires stop/resend after repairing the cause.
- Disable preserves credentials and affects next launches. For immediate removal
  of reusable auth, disconnect/remove and stop the affected chats; provider-side
  revocation outcome is separate and may fail even though local auth was destroyed.
  Stop/resend is the explicit process boundary; nothing cancels already-executing
  upstream work. Module disable/rollback alone does not revoke credentials/grants.
- Before an authorized host rollback, stop MCP-backed processes and disconnect or
  disable selected connectors as appropriate. Keep the additive schema intact;
  older module versions cannot roll back central state. Rolling to a host below
  contract v22 makes the v22 module incompatible, and the pre-round-2 host (v21)
  expects KMS envelopes: plaintext credentials written by round 2 are unreadable
  there (`key_unavailable`), so roll back only together with a disconnect.
  Retain old deployed artifacts needed for a separately authorized recovery,
  rather than deleting tables as part of rollback.

## Deterministic vs. live evidence

Local-only tests live in the per-package test directories. From the isolated host
worktree, run `uv sync --locked`, `sam validate --lint`,
`bash -n scripts/deploy.sh`, Python compileall and `git diff --check`. S6's
`agent/tests/test_mcp_3796_infra.py` asserts environment routing, URL
validation, CloudFront behavior, both deployment mappings and the absence of
key-service and callback configuration. The existing
`agent/tests/test_mcp_3796_cli_wire.py` drives the exact staged adapter through
stdio and fixture HTTPS using the official SDK; use the disposable PostgreSQL
fixture and `MCP_SDK_PYTHON_3796`, never a production database. Local fixture tests
are not committed under project policy.

These checks do not prove live provider consent, external log redaction, VM
networking or actual model tool exposure. Keep those as explicit rollout evidence.
