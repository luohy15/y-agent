---
title: CLI EC2 File Transfer
type: prd
project: y-agent
feature: cli-file-transfer
status: active
---

# CLI EC2 File Transfer

## Problem Statement

The operator needs a first-class, Mac-side way to push selected local files to the
EC2 host and pull files back later, using the same SSH identity already used for
day-to-day access. Ad-hoc rsync one-liners are easy to get wrong (host, remote
mkdir, dry-run, excludes) and do not share the CLI's known default VM target.
The original need was offline backup of valuable Mac data before a device
handover; the durable product need is a small, generic bidirectional transfer
surface under the `y` CLI, without baking personal inventory into the public
repo.

Historical inventory and cleanup context for the original backup motivation
lives outside this PRD (do not copy sensitive lists here):

- `pages/mac-cleanup-backup-plan.md` (private workspace inventory / ranking)
- `pages/plan-2826-y-upload.md` (delivery plan for the first upload ship)
- `pages/review-2826-y-upload.md` (review verdict and follow-ups for that ship)

## Solution

Own bidirectional EC2 file transfer under a single Click command group:

```
y file upload SOURCE...   [options]   # local Mac → EC2
y file download SOURCE... [options]   # EC2 → local Mac
```

Both directions shell out to system `rsync` over SSH, resolve the default host
from the authenticated API's `VmConfig` named `default` (with `--host`
override), preflight rsync presence and non-interactive SSH reachability, and
share the same safety knobs: dry-run, optional mirror delete, optional
checksum, repeatable excludes. Paths are always supplied by the user; the
command never embeds personal filenames or private directory inventories.

The flat top-level `y upload` shipped by todo 2826 is the historical surface
for the Mac→EC2 direction. Todo 2833 moves that behavior under `y file upload`
and adds the inverse `y file download`. After 2833, the public contract is the
`y file` group only (no parallel top-level upload/download verbs).

## User Stories

1. As a Mac operator, I want `y file upload PATH...` to push one or more local
   files or directories to the EC2 host, so that I can back up or stage data
   without hand-writing rsync.
2. As a Mac operator, I want `y file download PATH...` to pull one or more
   remote files or directories from the EC2 host to my Mac, so that restore and
   two-way sync use the same tool family as upload.
3. As an operator, I want both verbs under `y file`, so that transfer commands
   match other grouped CLI surfaces (`y chat`, `y bot`, …) instead of one-off
   top-level verbs.
4. As an operator, I want the default host to come from the authenticated API's
   default VM config, so that I do not retype `user@host` for every transfer.
5. As an operator, I want `--host <user@host|alias>` to override the default
   target, so that a non-default machine or SSH alias still works without
   changing config.
6. As an operator, I want auth to reuse my Mac SSH agent / `~/.ssh/config` only
   (no new secrets written by the CLI), so that the tool never materializes
   server-side keys onto the laptop.
7. As an operator, I want a non-interactive SSH preflight with a clear failure
   message when BatchMode auth fails, so that a missing key fails fast instead
   of hanging on a password prompt.
8. As an operator, I want a preflight that checks `rsync` is on `PATH`, so that
   a missing binary is explained before any transfer attempt.
9. As an operator uploading, I want each local `SOURCE` basename preserved under
   the remote `--dest` directory (default `~/luohy15/backup/mac`), so that
   multiple sources land predictably without me inventing remote paths per file.
10. As an operator downloading, I want each remote `SOURCE` pulled into a local
    `--dest` directory with basename preserved (mirror of upload layout rules),
    so that restore paths are obvious and symmetric.
11. As an operator, I want remote destination directories that use a leading
    `~/` to expand on the remote shell (not create a literal `~` directory), so
    that default home-relative destinations work on real hosts.
12. As an operator, I want `-n` / `--dry-run` to print the exact rsync command
    and transfer nothing, so that the first run on a new path is always safe.
13. As an operator, I want incremental rsync by default (archive mode, partial
    resume), so that re-running the same command only moves deltas.
14. As an operator, I want `--mirror` to opt into rsync `--delete`, so that a
    true mirror is available but never the default for a backup-style push.
15. As an operator, I want `--checksum` for a content-verify pass, so that I can
    catch size/mtime-blind mismatches when needed.
16. As an operator, I want repeatable `--exclude PATTERN` flags, so that build
    artifacts or junk can be skipped without hardcoding personal inventories.
17. As an operator, I want missing local upload sources to fail with a clear
    error before any network work, so that typos do not half-run.
18. As an operator, I want per-source progress headers and a final summary
    (including dry-run vs real), so that multi-source runs are readable.
19. As an operator, I want a non-zero exit when any source's rsync fails, so that
    scripts and humans can trust success.
20. As an operator, I want the CLI and help text free of personal filenames and
    private inventory lists, so that the public repo never re-embeds sensitive
    backup content.
21. As a maintainer, I want host resolution, preflight, rsync flag construction,
    and tilde-safe remote path handling shared between upload and download, so
    that the two directions cannot drift.
22. As a reader of docs, I want AGENTS/CLAUDE command snippets and `--help` to
    describe `y file upload` / `y file download`, so that discoverability matches
    the shipped surface after the regroup.

## Implementation Decisions

- **Command group**: Click group `file` registered on the root `y` CLI, with
  subcommands `upload` and `download`. Public surface after 2833:
  `y file upload`, `y file download`. Remove the flat top-level `y upload`
  once the group is in place (no long-lived dual surface).
- **Transport**: shell out to system `rsync` with `-e ssh` (or `ssh -p <port>`
  when the resolved target is non-22). Do not reimplement transfer in paramiko
  for this client path.
- **Baseline rsync flags**: `-a --compress --partial --human-readable` plus
  progress reporting as supported by the local rsync; add `--dry-run`,
  `--delete` (via `--mirror`), and `--checksum` when requested.
- **Host resolution**: if `--host` is set, use it; else `GET /api/vm-config/list`
  via the existing CLI API client / JWT session, pick the config named
  `default`, parse `vm_name` into `user@host` and optional non-default port.
  Never require direct database access from the Mac.
- **Auth model**: Mac-local SSH only (agent / config / default keys). Do not
  write `vm_config.api_token` (or any other server-side secret) to disk for this
  feature.
- **Upload destination**: default remote root `~/luohy15/backup/mac`; each
  local source path expands with `~` locally, must exist, and is synced so its
  basename lands under the dest root.
- **Download direction**: remote paths are the positional `SOURCE...`; local
  `--dest` is the directory that receives basenames. Same flag set as upload
  where it still makes sense (`--host`, `--dest`, `-n`/`--dry-run`, `--mirror`,
  `--checksum`, `--exclude`). Ensure local dest exists (or is created) before
  real transfers; dry-run must not require a successful remote write.
- **Tilde-safe remote mkdir (upload)**: when ensuring a remote directory, keep a
  leading `~/` unquoted for remote shell expansion and quote only the remainder;
  bare `~` stays unquoted. This is a shipped correctness constraint from 2826.
- **Privacy / generic surface**: user-supplied paths only. No named source
  groups, no default personal inventories, no citations of private backup
  inventories in code or help. Sensitive backup planning remains in private
  notes linked from Delivery Records / this Problem Statement.
- **Docs**: update CLI help and the Commands one-liner in project agent docs to
  the `y file` surface when 2833 ships.
- **Shared helpers**: extract common resolve / preflight / rsync-flag / remote-dir
  helpers so upload and download share one implementation of the hard-won
  edge cases (API host resolve, tilde mkdir, BatchMode preflight).

## Testing Decisions

- Prefer behavior-level checks over implementation snapshots: help text and
  usage errors for the `y file` group; classification of dry-run vs real flag
  sets; host override vs API default resolution (mock the API client); command
  argv construction for upload and download (source/dest sides swapped
  correctly); tilde-safe remote mkdir quoting cases (`~/path`, `~`, absolute).
- Keep end-to-end verification optional and environment-gated: a live SSH host
  is not assumed in CI. When a host is available, a dry-run then a small real
  round-trip (upload a temp file, download it back, compare) is the acceptance
  bar for 2833.
- Prior art: todo 2826 validated (a) unit-style construction of rsync/SSH
  commands, (b) real-host smoke after the tilde-mkdir fix, (c) privacy
  grep-clean checks so personal inventory strings never re-enter the module.
  Extend those patterns rather than inventing a new harness.
- Regression focus for 2833: regroup must not change upload semantics other
  than the command path; download must not invent a second host-resolution or
  auth path.

## Out of Scope

- Hardcoded personal file inventories, named backup groups, or
  credential-group gating in the public CLI (removed during 2826; stay out).
- Server-side / worker-initiated transfers using DB-stored SSH keys (that is a
  different auth world from Mac-side `y file`).
- Cloud object-store backends (S3/rclone) as an alternative transport.
- Automatic discovery of "what should be backed up" (git dirty scans, Photos
  library, Keychain, TCC-protected trees).
- Encryption-at-rest policy, key rotation, or credential lifecycle for the
  backup corpus (operator responsibility; see private backup plan notes).
- GUI / web UI for transfers.
- Preserving a long-term dual CLI surface (`y upload` plus `y file upload`).
- Changing the EC2 directory-structure scheme beyond the default dest root
  constant (directory layout ownership stays with the broader luohy15 layout
  work; this feature only needs a stable default dest string).

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 2826 | Ship Mac→EC2 `y upload` (rsync/SSH, API host resolve, tilde-safe mkdir, generic SOURCE paths) | - | `pages/plan-2826-y-upload.md` | - | `pages/review-2826-y-upload.md` | shipped |
| 2833 | Regroup under `y file`; add EC2→Mac `y file download` mirroring upload | - | - | - | - | planned |

Related private context (not requirement text): `pages/mac-cleanup-backup-plan.md`.
