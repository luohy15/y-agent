---
title: MCP Connectors
type: prd
project: y-agent
feature: mcp-connectors
status: active
---

# MCP Connectors

## Problem Statement

Claude Code-backed y-agent sessions currently exclude ambient MCP configuration.
Users cannot centrally connect an external MCP server, authorize it, select its
tools and reliably make those tools available across their bots. Configuring a
server manually on a VM does not provide an authoritative, owner-scoped switch,
a web authorization flow or a clear explanation of what a running session uses.

## Solution

Provide an MCP connector module for remote HTTPS Streamable HTTP servers, with
Alpha Vantage as the first preset. The module manages configuration, authorization,
tool approval and enablement through web and CLI surfaces. The host owns the
runtime contract, credential custody and enforcement needed by session execution.

One connector switch applies to all Claude Code-backed bots belonging to its
owner, including relay-backed models using that harness. Changes apply on the
next actual process launch, including conversation resume. They do not interrupt
or reconfigure an already-running process.

OAuth is a first-class web flow, with an API-hosted callback, centrally encrypted
tokens and automatic refresh where supported. Static secret headers and no-auth
connections are also supported, as mutually exclusive authentication modes.
Only explicitly approved tools are available. Connector failures are isolated,
reported visibly and do not make unrelated chat work unavailable.

This PRD synthesizes the completed requirements interview for todo 3796. Roy
confirmed Q1–Q10, including the amendment requiring OAuth in v1, on 2026-09-30.
Detailed protocol, storage and deployment design must satisfy these requirements
before implementation. Requirements are settled; implementation and deployment
are not complete.

## User Stories

### Configuration and scope

1. As the owner, I want one place to list my connectors and their endpoints,
   authentication modes, desired enablement and connection status.
2. As the owner, I want to add and edit a remote HTTPS Streamable HTTP server
   without changing code or redeploying the application.
3. As the owner, I want an Alpha Vantage preset so that its correct MCP endpoint
   and supported authentication choices do not require guesswork.
4. As the owner, I want new connectors disabled until configured, authenticated
   when necessary, validated and given an explicit tool policy.
5. As the owner, I want a single switch shared by all my Claude Code-backed bots,
   without maintaining per-bot or per-chat overrides.
6. As the owner, I want non-Claude-Code inline backends left unchanged rather
   than advertised as MCP-capable.
7. As the owner, I want connector configuration isolated from other owners, with
   management restricted to the configured maintainer under the module contract.
8. As the owner, I want web and CLI operations for list, add/edit, connect,
   connection test/tool discovery, tool selection, enable/disable, disconnect
   and removal, using the same authoritative state and validation.
9. As the owner, I want disconnect distinguished from disable: disable preserves
   authorization for later use; disconnect removes reusable credentials and
   requires reconnection. Removal also removes the saved connector.

### Authorization and credentials

10. As the owner, I want Connect to open provider consent in my browser and
    return to y-agent, without logging into the execution VM.
11. As the owner, I want the CLI to initiate that same authorization flow and
    show a URL, rather than maintain independent VM-local OAuth credentials.
12. As the owner, I want authorization success, cancellation, expiry and failure
    shown clearly, without confusing a saved endpoint with a working connection.
13. As the owner, I want tokens refreshed automatically when supported, including
    during long-running sessions, and Reconnect shown when renewed consent is
    required.
14. As the owner, I want access tokens, refresh tokens and client secrets stored
    encrypted centrally and excluded from ordinary reads, logs and artifacts.
15. As the owner, I want static header credentials accepted through write-only
    web fields or CLI hidden input/stdin, with explicit replace/clear actions.
16. As the owner, I want one explicit authentication mode per connector, so a
    static key cannot ambiguously override an OAuth identity.
17. As the owner, I want no-auth servers supported without fabricated credentials.
18. As the owner, I want endpoint or authentication-identity changes to require
    fresh validation and tool approval rather than send old credentials to a
    different server.
19. As the owner, I want disconnect to remove y-agent's reusable credential and
    report provider revocation failures honestly where revocation is supported.

### Tool authority

20. As the owner, I want authenticated tool discovery before choosing which
    tools bots may call.
21. As the owner, I want names and descriptions displayed for explicit approval,
    with provider annotations shown as hints rather than safety guarantees.
22. As the owner, I want Select all to approve only the currently discovered
    tools, not future additions by the server.
23. As the owner, I want new provider tools excluded until I explicitly approve
    them, while removed tools are shown as unavailable.
24. As the owner, I want the approved subset enforced in actual MCP discovery
    and dispatch, even though the existing harness runs with bypassPermissions.
25. As the owner, I want approved tools to run unattended without per-call
    permission prompts, preserving background and delegated workflows.
26. As the owner, I want resources, prompts or alternate dispatch methods unable
    to bypass the approved tool boundary.

### Session lifecycle and failure

27. As the owner, I want each new process launch to use current connector
    configuration, including a launch resuming an existing conversation.
28. As the owner, I want running processes left uninterrupted by edits, with a
    clear notice that disable is not immediate revocation.
29. As the owner, I want stop followed by resend/resume to apply current settings
    without needing a new chat identity.
30. As the owner, I want steer and worker monitor handoff distinguished from a
    new process launch, so neither falsely claims to adopt new configuration.
31. As the owner, I want configured state and the launch's applied state to be
    distinguishable without exposing credentials.
32. As the owner, I want an unavailable or expired connector isolated, while
    built-in tools and other healthy connectors remain usable.
33. As the owner, I want a visible sanitized reason for missing tools and an
    actionable reconnect/retry path, not a silent omission.
34. As the owner, I want failed tool calls returned as errors, never invented
    results or silent substitution of another service.
35. As the owner, I want bounded connection and refresh attempts so one provider
    cannot indefinitely stall session startup.
36. As the owner, I want failures to deny that connector's access, never inherit
    ambient configuration, stale unverified permissions or another identity.

## Implementation Decisions

### Confirmed scope and lifecycle

The owner-wide switch, launch-boundary application, remote HTTPS transport,
required OAuth, central credential custody, tool allowlist and isolated failures
are confirmed decisions. No per-bot or per-chat override exists in v1.

Desired enablement, authentication readiness, last test result and applied launch
configuration are separate facts. A saved switch is not evidence of connection.
A connection test reports an observation, not a continuous health guarantee.
Persist only sanitized connector identities/revisions and status needed to explain
launch behavior; do not store credential-bearing launch configurations in chat
history or process-monitor records.

A launch snapshots connector selection and approved tool policy. Steer and a
worker handoff monitoring the same process retain that snapshot. Credential
refresh may occur without widening that snapshot. Disconnect, deletion or
provider revocation can cause a running connector to fail authentication; the
no-hot-revocation contract does not guarantee continued access after credentials
are removed. No UI action promises to terminate an in-flight provider call.

### Module and host boundary

Use the existing module architecture, not a new worker plugin system. The module
owns web/CLI management and its API facade. Worker-consumed connector state,
authorization transactions, central credentials, runtime enforcement and launch
integration belong to the host runtime kernel, exposed to the module through
narrow, versioned, owner-bound capabilities, following the Bot runtime precedent.

The implementation plan defines the exact schema, capability names, contract
version bump and migration SQL. Migrations remain maintainer-applied. Public API
payloads use public identifiers, never internal integer primary keys. No module
bundle is imported into the worker. Module disable or code rollback is not a
credential-revocation operation; runtime state and management-code lifecycle must
be documented separately.

Keep strict MCP isolation. Supply only the host-resolved launch configuration;
do not enable ambient user/project MCP configuration or alter global Claude Code
settings. Use protected per-launch material rather than secret-bearing command
arguments. The exact runtime adapter is a planning decision, but must enforce
both the real tool allowlist and refresh semantics. A launch-only bearer token
with no renewal path is insufficient. A prompt-level rule or built-in tool list
is not sufficient MCP authorization enforcement.

### OAuth contract

Use authorization code with S256 PKCE, short-lived single-use state bound to the
initiating owner and connector, and a fixed API-hosted HTTPS redirect URI. The
callback is a narrowly scoped host route: provider redirects cannot be assumed
to carry y-agent's local-storage Bearer token. Validate the transaction and issuer
before exchanging a code. General module routes remain authenticated.

Use standards-based MCP protected-resource/authorization-server discovery and
advertised registration where supported. Support explicitly configured client
registration credentials when automatic registration is unavailable, without
provider-specific login scripts. Clearly report unsupported discovery or grant
requirements. Exact supported metadata/authentication variants are frozen in the
plan and tested against Alpha Vantage, not inferred from an old task or advertised
as universal OAuth compatibility. No arbitrary caller-supplied redirect targets.

Browser surfaces receive provider authorization URLs and sanitized outcomes,
not tokens. Encrypt stored access/refresh tokens, OAuth client secrets and static
header values with deployment-managed key material outside the database. Define
key rotation and recovery in the plan. Serialize concurrent refresh for one
credential, persist rotated refresh tokens atomically, and reject late exchanges
or refresh writes that would resurrect disconnected/replaced authorization.
Bound retries and distinguish transient provider errors from invalid grants
requiring Reconnect. Never automatically replay a possibly executed tool call
merely because the connection failed.

The same credential service supports OAuth, static-header and no-auth modes.
Static bearer tokens are manually managed values, not automatically refreshed
OAuth sessions. Credential values are write-only through management surfaces.
Do not place secrets in endpoint URLs, command arguments, ordinary read payloads,
chat messages, generated bundles or Git. Redact callback codes, tokens and headers
from diagnostics. An agent running under the same VM OS user is not isolated from
files readable by that user; make no stronger sandbox claim.

### Network and tool boundary

Only remote HTTPS Streamable HTTP endpoints are supported. Validate network
destinations for connector calls, OAuth discovery, registration, exchange and
redirects. Block loopback, link-local/metadata and private/internal destinations,
including DNS resolution and redirect bypasses. Bind credentials to validated
origins and do not forward authorization across an unapproved redirect. Treat
provider descriptions, metadata and errors as untrusted content.

Approval uses explicit tool identities scoped to a connector. Empty approval
means no tools, not all tools. Newly discovered identities are never approved by
wildcard or inferred from read-only annotations. Removed approved tools remain
unavailable. Tool descriptions are not guarantees that a provider will keep the
same behavior under an existing name. Endpoint/identity replacement invalidates
connection validation and prior tool approval for subsequent launches.

V1 exposes tools only. Resources and prompts are not alternate unrestricted
capabilities. Connection validation discovers tools without executing arbitrary
tools. Live tool smoke tests require a deliberately chosen, authorized operation.

### Alpha Vantage first acceptance target

The preset uses `https://mcp.alphavantage.co/mcp`, not the landing-page URL.
OAuth must be exercised end to end; static API-key mode must not substitute for
that acceptance. The optional static-key mode uses the supported `apikey` header
rather than a query-string secret. Roy enters credentials only through the
approved setup surface, not interview messages or committed documentation.

Local server source supports raw-key headers and advertises registration,
authorization-code/refresh grants and S256 PKCE. This is design evidence, not a
fresh production verification. Implementation must establish the current deployed
contract before reporting success.

## Testing Decisions

Test observable authorization, lifecycle and failure behavior, not just command
construction. Use fake MCP/OAuth providers and controllable time/network errors
for deterministic local tests. Keep tests local-only under project policy.

- Exercise all three authentication modes, invalid setup and write-only reads.
- Verify owner isolation and maintainer gating across API, CLI and runtime;
  guessed connector identifiers must never expose another owner's credentials.
- Exercise OAuth success, denial, expired/replayed state, PKCE mismatch, issuer
  mismatch, invalid redirects and unsupported metadata. A callback without a
  valid transaction cannot mutate authorization.
- Test refresh during a long-lived process, concurrent refresh, rotated tokens,
  refresh rejection, and disconnect/replace racing with callback or refresh.
- Verify no secret appears in commands, logs, error payloads, status reads,
  transcripts or module bundles. Verify key-unavailable failures deny access.
- Test network destination validation across discovery, exchange, connection,
  redirects and DNS changes; blocked targets receive no credentials.
- Demonstrate that unapproved and newly added tools cannot be listed or called
  through the actual runtime path, including with bypassPermissions. Select all
  is a snapshot, and resources/prompts cannot evade it.
- Test fresh launch, resumed launch, steer, monitor handoff, disable, removal and
  stop/resend. Applied policy stays stable within an existing process; a new
  launch adopts changes and never loads ambient servers.
- Inject timeout, malformed response, missing secret, invalid grant and provider
  outage. Healthy tools remain usable, errors are visible and sanitized, attempts
  are bounded, and no failed connector silently regains access through fallback.
- Verify module rollback does not falsely claim to roll back credentials or
  runtime policy; older host-contract incompatibility is explicit.
- Complete an authorized Alpha Vantage OAuth flow, discovery, explicit tool
  approval, one bounded tool call and subsequent disable/resume check. Separately
  verify static-header behavior. Do not claim live acceptance from unit tests.

Static UI checks suffice unless Roy explicitly requests browser-driven testing.
Infrastructure provisioning, callback registration, live credential use and
publication require the applicable authorization; requirement approval alone is
not release authorization.

## Out of Scope

- Other execution backends, per-bot/per-chat overrides and public multi-user
  connector sharing or a connector marketplace.
- Stdio servers, local command execution, legacy SSE transport and private-network
  MCP endpoints.
- Immediate hot reload, guaranteed in-flight cancellation or hot revocation of
  running sessions. Stop/resend is the explicit launch-boundary workflow.
- Per-call human approval, automatic approval of new tools and a claim that
  provider annotations prove a tool safe.
- VM-local OAuth login, independent CLI token stores, provider-specific OAuth
  scripts and a guarantee of compatibility with every OAuth server.
- MCP resources/prompts, arbitrary tool execution as a connection test, or
  automatic replacement of an unavailable provider.
- General chat lifecycle, routing and steer mechanics, owned by
  [chat-core](chat-core.md), [bot-routing](bot-routing.md) and
  [chat-steer](chat-steer.md). This feature only adds the connector launch contract.
- General module packaging, publishing and rollback infrastructure, owned by
  [module-system](module-system.md).

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3796 | Owner-scoped MCP connector management and Claude Code integration, Alpha Vantage first | - | - | `pages/decision-3796-mcp-interview.md` | - | Requirements settled; coordinator review pending; not implemented |
