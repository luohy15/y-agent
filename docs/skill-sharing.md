# Private skill sharing

`y skill` publishes one selected directory from `~/.agents/skills/<name>` through
an authenticated API. It does not synchronize a config tree or expose anonymous
bundle downloads.

```bash
y skill publish note --node mac --version 3.2
y skill list
y skill unshare note
```

`--node` is required and repeatable. Publishing replaces the skill's complete
node set. Nodes must exist, be enabled and use relay authentication. `macmini`
and subscription authentication are excluded. Unshare removes all pins for that
skill; it does not delete historical bundles or node caches. Running sessions
keep their launch snapshot; the next launch uses the updated pins.

## Bundle contract

Bundles contain regular files only, including `SKILL.md`. Names are lowercase
letters/digits/hyphens (64 characters maximum). Symlinks, hidden path components,
absolute member paths, traversal and special files are rejected. Limits are 256
files and 4,000,000 bytes both compressed and expanded. The canonical manifest
includes sorted paths, SHA-256 hashes, executable flags and dependencies; its
SHA-256 is the bundle identity. A version is only a display label.

The CLI scans text files for `../<skill>/` references and concrete
`/Users/roy/...` references. Referenced skills must also be pinned on the target.
Absolute references must be concrete files readable by the publisher; their
hashes are checked in place on the target, never copied or rewritten. Templated
or directory absolute references need to be removed or made concrete before
publishing. The API recomputes hashes and checks that detected references match
the manifest. This scan is conservative, not a parser for arbitrary programs or
an assurance that a skill has no dynamically constructed dependencies.

## Launch and restore

The worker reads owner-scoped pins and stages over the node's existing SSH
connection, with no API credential sent to the node. Verified cache generations
live below `~/.y-agent/skill-cache/<bundle_sha>/`. A corrupt cache is refetched
into a new generation rather than overwritten under a concurrent session.

If every pinned local tree already matches, no overlay is needed. Otherwise a
private `/tmp/y-skill-<chat-hash>-<random>/` config directory links existing
settings, projects, plugins and non-pinned skills; pinned skill directories are
materialized from verified cache bytes. `CLAUDE_CONFIG_DIR` applies only to that
launch. Exit, explicit stop and the next launch clean the chat's overlay, not
the cache or original skill files. A hard host crash can leave an overlay until
the next launch of the same chat.

Missing dependencies, unavailable storage without verified cache, corrupt
bundles and non-relay pins fail closed with `skill_*` errors. Restore by
`y skill unshare <name>` and launch again. Nothing edits the original skills.

## Deployment prerequisites and verification

Apply the additive `migration/4232_skill_share.sql` before deploying the API and
worker. There are no automatic migrations. Bundles use the existing private S3
bucket under `skill/<public_user_id>/<name>/<sha>.zip`; all four S3 public-access
blocks must be enabled. Without S3, `Y_AGENT_SKILL_BUNDLE_DIR` selects a shared
private local store (default `~/.y-agent/skill-bundles`); API and worker must see
the same store. The CLI and worker must be upgraded with the API.

After successful deployment, record the mac local `note/SKILL.md` hash and skill
count, publish `note` to `mac`, then launch a mac chat that loads `note` and prints
its loaded path and version. Expect version 3.2 and `## Tags` under the overlay;
load a non-pinned skill too. Recheck original hashes/counts. Unshare and launch a
new mac chat: expect its original local version/path. A default-node chat must
remain overlay-free. This live proof is separate from local deterministic tests.

The existing `y chat --skill` caller-local name preflight remains unchanged:
use a publishing machine with that skill installed, or request loading it in the
message when dispatching from a machine without that local name.
