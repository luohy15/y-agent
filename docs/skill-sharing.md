# Private skill registry

Publish committed source, then install an exact immutable version on a relay node:

```bash
y skill publish note@3.2.0 --source /Users/roy/luohy15/.agents --sha HEAD
y skill list
y skill show note
y skill install note@3.2.0 --node mac
y skill status --node mac
y skill upgrade note --node mac
y skill rollback note --node mac
y skill uninstall note --node mac
```

Versions are canonical `MAJOR.MINOR.PATCH`, not front-matter labels. No ranges,
prereleases or build metadata. The latest pointer follows numeric semver order.
Republishing identical content at an existing version is a no-op; changing its
content is a conflict. Publish does not install. Install requires an exact version
and refuses to replace a different installed version; upgrade selects latest or
an explicit version; rollback swaps current and previous versions.

## Source and storage

The CLI resolves `--sha` (default HEAD) in `--source` (default the path above),
reads `skills/<name>/` with `git ls-tree` and `git cat-file`, and records the full
source commit and normalized origin repository. Dirty worktree bytes are not
published. Symlinks, gitlinks, hidden files, traversal and special files are
rejected. Bundles require `SKILL.md`, allow at most 256 files and 4,000,000 bytes
compressed or expanded. Canonical manifests include hashes, executable bits and
dependencies. The API verifies bundle identity and exposes no anonymous download.

Private bytes use `skill/<public_user_id>/<name>/<bundle_sha>.zip` in the existing
S3 bucket (all four public-access blocks required). Without S3,
`Y_AGENT_SKILL_BUNDLE_DIR` selects a shared API/worker filesystem store, default
`~/.y-agent/skill-bundles`. Registry metadata lives in `skill`, `skill_version`,
and `skill_install`, isolated by owner.

The static scan detects sibling skill references and concrete `/Users/roy/`
file references. Required skills must be installed on the node at installation
and launch. Absolute files are hashed and verified in place, never transferred.
Dynamic references and cross-skill version compatibility are not inferred.

## Shared node generations

Launches snapshot installs and use the existing SSH connection, never node-side
API credentials. If all installed local trees match, no overlay is needed.
Otherwise `CLAUDE_CONFIG_DIR` points to
`~/.y-agent/skill-overlay/<node>/<digest>/`. Installed skills are materialized;
other local skills and config entries are symlinked. The digest covers installed
bundle identities and local config/skill entry names, not uninstalled file bodies
(which remain live through their symlinks).

Complete generations are atomically renamed from `.tmp/`; concurrent publication
must reuse a verified winner. Corrupt final directories are retained while a unique
sibling holds repaired content. Verified cache generations persist separately in
`~/.y-agent/skill-cache/<bundle_sha>/`.

Launch references live under `.refs/<generation>/<chat_hash>`. Session exit,
explicit stop and next launch remove only that chat's references, not shared
bytes. An opportunistic sweep runs at each launch, including zero installs. It
removes temporary builds older than one day and unused generations older than
`Y_AGENT_SKILL_OVERLAY_TTL_DAYS` (default 7). Unknown process or tmux state retains
data. No timer is created. Uninstall is DB-only: new launches immediately use
local discovery, running sessions keep their generation, and stale generations
wait for a later launch sweep. Cache pruning is out of scope.

Only owner-bound enabled relay nodes accept install/upgrade/rollback. `macmini`
and subscription nodes are excluded. Uninstall/status remain available when a
node is disabled. Dependency/store/verification failures close the launch rather
than silently selecting stale local skills.

## Deployment and mac acceptance

Apply the additive `migration/4232_skill_share.sql` before API/worker deployment;
upgrade the CLI with them. There are no automatic migrations. Verify schema and
existing Lambda S3 permissions before publication. Wait for successful deployment
before testing live behavior.

On mac only, record the original note hash and skill count. Publish `note@3.1.0`
and `note@3.2.0` from the appropriate commits. Install 3.1.0 then upgrade to 3.2.0
(to establish rollback history). Two chats must load the same digest directory,
with unchanged directory mtime, and the shared 3.2 body including `## Tags`.
A non-installed skill must still load; original hashes/counts must remain unchanged.
Rollback restores 3.1, upgrade selects 3.2, uninstall restores local discovery.
Backdate an unused generation and verify a later launch sweeps it. Default-node
launches without installs remain overlay-free. Never test macmini.

The caller-local `y chat --skill` name preflight remains unchanged.
