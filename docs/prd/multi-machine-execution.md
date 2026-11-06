---
title: Multi-machine execution
type: prd
project: y-agent
feature: multi-machine-execution
status: active
---

# Multi-machine execution

## Boundary

A chat runs Claude Code on one explicitly selected execution node, through the
same chat interface used for EC2 sessions. The central EC2 remains the
orchestrator and SSH jump anchor. Host APIs, state, dispatch, credentials custody
and the worker lifecycle remain central; the target holds its process, workspace,
stdin, stdout and exit file. This is not a separate job API or a new agent backend.

The owner's MacBook is the first non-default node. The Mac Mini / US work-only
node is excluded until its separate onboarding and data-isolation work (todo
4214). Do not add it to the registry for personal tasks. There is no automatic
node selection, workspace synchronization, credential replication or remote
machine provisioning.

## Node registry and selection

The registry is the authenticated owner's `vm_config` rows, not a separate
execution-target table. Adding a supported node is a configuration write; it
does not require a code change or deployment.

| Field | Contract |
|---|---|
| `name` | Node identifier accepted by `y chat --on <name>`. `default` is the orchestrator and jump anchor. |
| `vm_name` | SSH address in `[ssh:]user@host:port` form. |
| `api_token` | SSH private key. An empty key on a non-default row inherits the default node's key. Keys are not returned by node list/show. |
| `work_dir` | Default workspace on that node; it must already exist with the required files. |
| `platform` | `linux` (also the meaning of NULL) or `darwin`; derives binaries, PATH and runtime capabilities. |
| `data_scope` | `personal` (also the meaning of NULL) or `work`. Visible metadata only, not an enforced sandbox or routing rule. |
| `enabled` | Soft enable/disable for admission and launch. Stop and monitoring can still resolve a disabled row. |
| `auth_mode` | NULL or `relay` injects the selected bot's relay environment at launch. `subscription` omits it and unsets it in the shell, so the node uses its own Claude login. The node decides; a chat has no credential preference. |
| `ec2_instance_id`, `ec2_region`, `last_up` | Existing wake metadata, used on the default anchor rather than the jump node. |

`chat.execution_target` snapshots the selected **name**, not the node's mutable
connection settings. NULL, empty and the legacy `ec2` value mean `default`.
Non-default names such as `mac` are stored as-is. Existing chats cannot be
retargeted, including a chat originally created on the default node. Connection
settings are resolved from the row; editing that row does not rename a chat's
snapshot and can affect later connections.

No `--on` on a new chat means `default`. An existing chat resumes its stored
node. Admission and launch use owner-bound strict resolution: unknown,
wrong-owner or disabled nodes fail rather than substituting another machine.
The `mac` name is an ordinary registry row. There is no environment-variable
fallback for it. An unusable address, key or SSH tunnel fails closed, never
reroutes to EC2. Admission resolves uncached; worker layouts have a 30-second
cache.

Generic VM commands, including file/git/terminal operations, stay on `default`.
Non-default registry rows are chat-only and are filtered out of the file/git VM
picker. A matching workspace must not auto-select a non-default node. Workspace
lookup filters by owner, exact path and `name=default`, rather than selecting an
arbitrary matching row. Different nodes may share the same workspace path;
`(user_id, name)` remains their unique identity. Existing databases need the
legacy `uq_vm_config_user_work_dir` constraint removed via the separately applied
`migration/4204_node_shared_work_dir.sql` before assigning duplicate paths. No
replacement default-only workspace index is needed because owner/name uniqueness
already permits only one default row per owner. No rows or tables are removed.

## CLI and HTTP contract

- `y node list`: owner-scoped rows, default first, then name order.
- `y node show <name>`: key-free JSON for one row.
- `y node add <name> --host <host> --user <user> [--port 22]
  [--platform linux|darwin] --data-scope personal|work [--work-dir <path>]
  [--key-file <path>|--inherit-key] [--auth-mode relay|subscription]`: create or
  update a non-default row. A new row without a key inherits the default key.
  An omitted key on an update preserves the existing key. The node must already
  authorize the chosen key. An omitted `--auth-mode` preserves the stored mode;
  a new row defaults to relay. `y node list` prints an AUTH column. `y node show`
  includes `auth_mode` in its JSON (NULL is reported as `relay`).
- `y node enable <name>` / `y node disable <name>`: change admission eligibility.
- `y chat --on <name> ...`: choose the node for a new chat; subsequent messages
  use the same chat ID and stored target.

Node commands use the existing host `/api/vm-config` controller. GET
`/api/vm-config/list` returns name, address, workspace, platform, scope, enabled,
`auth_mode`, `is_default`, `chat_only` and wake metadata, never the private key.
POST `/api/vm-config` creates/updates a row. An omitted key, enabled flag or
`auth_mode` preserves that value on a non-default update. The default-node
write preserves an omitted `auth_mode` the same way. A value outside
`relay` / `subscription` is 422. POST `/api/vm-config/{name}/enable` and
`/disable` toggle a non-default row. The existing DELETE `/api/vm-config?name=...`
refuses the default node or any node pinned by a chat (409); `y node` offers no
hard-delete command. The existing full-config path still manages the default
row, outside node-edit rules.

Chat creation and dispatch use the existing chat endpoints and their optional
`execution_target` field. Unknown/disabled targets and attempts to change an
existing chat's target are rejected with 422. Images are rejected on jump nodes.
Backend contract v32 adds the owner-bound `bot_config_set_subscription_tiers`
capability and an `auth_mode` argument on the pure `bot_tier_pools` projection.
Backend contract v33 adds the owner-bound `bot_config_set_sub_ref` capability.

## Runtime and transport

For `default`, the worker uses the existing direct EC2 SSH runtime. For every
other node, it opens a Paramiko `direct-tcpip` channel through the default SSH
session, then a second SSH connection to the node. Wake-on-demand applies to the
anchor only. A laptop must already be reachable and have SSH, tmux, Claude Code,
its authentication, workspace and required tools/skills ready.

The existing detached launch skeleton starts Claude Code in node-local tmux on
the `y-agent` socket. Input and output remain files on that node. The worker
streams output and sends steer messages through the same chat lifecycle,
including Lambda lease handoff and monitoring. Process records carry the target
name so resumed monitoring and stop resolve the same node. An SSH disconnect is
not proof that the remote process stopped; tmux may continue running. Stop uses
the node's transport and teardown command, including when the row is disabled.

Platform profiles deliberately stay small:

- `darwin`: `/opt/homebrew/bin/tmux`, `/Users/<user>/.local/bin/claude`, a derived
  PATH including Homebrew and the user's local binaries, and `/tmp` runtime
  files. No heartbeat or orphan reaper.
- `linux`: the existing `tmux`/`claude` binaries and heartbeat behavior. Orphan
  reaping is available only on the direct default transport.
- Every jump node: no image attachments or transcript ingest. These facilities
  remain on the default transport. There are no per-node binary/path overrides.

The node registry is not a permission boundary for Claude's actions. A selected
node may receive chat content and use its local tools and authentication. The
`data_scope` label does not prevent personal content reaching a work node, nor
does removal of the old bounded-job validator provide such a guarantee. Keep
work-only nodes out until isolation is implemented and verified separately.

The worker reads `auth_mode` on every launch, including resume and continuation.
Relay mode exports `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` and
`_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL` as it does today. Subscription mode
removes those plus `ANTHROPIC_API_KEY` from the launch environment and runs
`unset` on all four before any export, so a stale shell cannot keep the relay
token. No relay credential is sent to the node. Inline backends never receive
this environment. The worker resolves the node's auth mode before choosing a
bot. A layout is cached for 30 seconds, so an edit can take that long to affect
the next launch.

`bot_config.subscription_tiers` is a nullable JSON tier-to-weight map. NULL
excludes a bot from subscription pools. A nonempty map declares independent
subscription tier membership: each key must be a supported tier and each value
must be null or a finite nonnegative number. Invalid stored maps are treated as
absent. The node's auth mode selects the map: relay uses `tiers` and its legacy
mirrors; subscription uses only `subscription_tiers`. Membership in the other
map has no effect. Relay selection is unchanged.
Automatic selection excludes an explicit zero even when it is the sole
candidate; an unset weight remains usable only when sole. Multi-bot pools draw
only positive weights. Explicit pins bypass weights. The runtime, pool
projection and effort preflight share the same viability predicate. An empty requested tier falls back to the
subscription tier2 pool. An empty subscription tier2 pool raises
`BotAuthModeError`, never the relay global default. An explicit ineligible bot
pin or re-bot fails the launch without substitution. A sticky bot that lost
eligibility is re-pooled and the accepted name and tier are persisted.

The narrow setter is the only write path for the subscription map; full bot
upserts deliberately omit it so an older module cannot clear it. None clears
the map; an empty map is rejected. Apply
`migration/4224_bot_subscription_tiers.sql` before deploying host contract v32,
then publish the Bot module requiring v32 before configuring weights. The
superseded scalar column remains physically present for rolling v31 readers,
but v32 neither maps nor reads/writes it. No backfill or column DROP is included.
The Bot editor saves Relay Tiers and Subscription Tiers independently; clearing
a subscription tier row removes that key from the map. The
operator configuration uses existing `sonnet` (tier2, relay weight 0,
subscription weight 1) and `opus` (tier1 only, relay weight 0, subscription
weight 1), without adding bots. Relay tier0 is intentionally empty; tier0
requests without effort fall back to tier2, while an explicit effort fails
when no candidate declares it. Subscription tier1 serves opus and tier2 serves
sonnet. Moving opus out of tier0 requires the Bot module's `--allow-empty-tier`. Model strings are shared across auth modes:
`sonnet[1m]` was verified with the node's subscription login, so no model override
is needed. The API effort preflight remains on the relay universe; launch checks
reject a subscription-only effort mismatch.

A pointer bot (`ref_bot_name` set) resolves by the node's auth mode on a pure
name pin (no backend and no tier filter). Relay follows `ref_bot_name` and
ignores `sub_ref_bot_name`; depth, cycle, and missing-target errors stay as
they are. Subscription follows `sub_ref_bot_name` and never follows
`ref_bot_name`. An unset subscription ref resolves through the subscription
tier2 pool, the same selection as a dispatch with no bot name. An empty pool
raises `BotAuthModeError` naming the pointer. A stored target that is missing,
disabled, itself a pointer, or no longer subscription-eligible raises
`BotAuthModeError` naming the pointer and the target, with no relay fallback
and no substitution. `--bot <pointer> --tier <tier>` keeps the previous
behavior. `bot_config.sub_ref_bot_name` is a nullable varchar with no backfill.
`bot_config_set_sub_ref` is the only write path: the row must already be a
pointer, and the target must exist for the same owner, be enabled, not be a
pointer, and have a nonempty `subscription_tiers`. A self-reference is
rejected. None clears the column. Full bot upserts omit it, so an older module
cannot clear or forge it. Renaming a bot cascades to both `ref_bot_name` and
`sub_ref_bot_name`. Apply `migration/4224_sub_ref_bot_name.sql` before
deploying host contract v33, then publish the Bot module requiring v33 before
setting a subscription ref.

Jump-node result `modelUsage` still updates cumulative chat tokens and context
usage. Subscription launches do not enter relay spend (`model_usage_daily`
source `crs`). Jump nodes skip per-request transcript usage and context analysis
because `ingest_transcripts=False`; this feature adds no subscription cost
attribution.

Transcripts stay on the node that wrote them, under
`$HOME/.claude/projects/<cwd with slashes replaced by dashes>/<session>.jsonl`.
The same work directory produces the same project key, so a copied `.jsonl` can
be resumed, but the launch path does not copy transcripts. Jump nodes do not
ingest them. The only restore hook is a hardcoded assets path, not a sync. A
chat therefore resumes only on the node that ran it unless that file is copied
to the target. Sharing a work-directory string is not a workspace sync: do not
copy the EC2 workspace root onto a work-only node.

## Retired bounded-job interface

The former Codex browser-job implementation is retired. `y remote-job` and
`/api/remote-jobs` are removed, including the runner, supervisor, storage code and
worker launch step. There is no replacement alias or browser-job submission
path. The worker logs and acknowledges legacy `task_type=remote_job` deliveries
for one release without launching a process, updating a row or creating a
completion receipt.

The UI-only Machine module that presented those routes is retired with them. Its
authoring source is removed from `code/y-module/machine`. Deleting the deployed
module (`y module delete machine`) is the final step, run after that source
change is reviewed; until it runs, a previously published version can still
mount the Machines panel and detail. There is no replacement module and no module
API. Deletion removes deployed module metadata and bytes only; it does not mutate
host code, node registry rows or tables.

The physical `remote_job` and `execution_target` tables and their existing data
are retained. They are not the node registry, and deleting their ORM code does
not drop them. Table cleanup requires separate explicit approval. Node
configuration continues to live in `vm_config` and is unaffected by this
retirement.

Before removing the old runtime, finish or account for any old active jobs;
removing routes is not remote cancellation and does not prove termination.
Before removing the transitional Mac configuration, create and verify the
owner's `mac` row. Existing chat targets need resolvable registry rows.

## Acceptance

Deterministic offline checks use fake rows and transports, not a database:

1. Default aliases resolve to the owner's default row; an unknown or disabled
   target fails. Setting the former Mac environment variable cannot resolve a
   missing `mac` row. Stop/monitor can resolve disabled rows.
2. A configured Darwin row produces the jump transport, derived Mac binaries
   and inherited key behavior. Default execution retains its direct profile.
3. New-chat admission accepts a registered node and rejects retargeting,
   wrong-owner/unknown/disabled rows and images on jump nodes.
4. Node responses do not expose keys; omitted update fields preserve keys and
   enabled state; default and referenced-node deletion remain guarded.
5. Retired routes, command registration and executable job sources are absent,
   and the Machine module source is absent from `code/y-module/machine`.
   Legacy queue payloads log and return done, without invoking a runner or chat.
   No table-drop migration is part of retirement.

After the corresponding host deployment succeeds, verify `y node list`, then
create a chat with `y chat --on mac` and check its output, machine chip, follow-up
message and stop behavior in the existing chat interface. Disable a disposable
registered node and confirm that new launches reject while stop/monitor of an
existing chat remain available. A newly registered supported node should work
without another deploy once its prerequisites are in place. Verify authenticated
requests to `/api/remote-jobs` return 404, the upgraded CLI has no built-in
`remote-job` command, and, once the deployed module is deleted, `y module list`
has no `machine` row, so no Machines panel or detail is mountable. These are
post-deploy acceptance steps, not claims that a local build verifies live
transport, schema or process termination.
