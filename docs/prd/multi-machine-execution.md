---
title: Multi-machine execution
type: prd
project: y-agent
feature: multi-machine-execution
status: active
---

# Multi-machine execution

## Boundary

The central EC2 remains the orchestrator. A remote machine is an operation target, not a chat backend. The initial slice supports only the owner's existing `ssh mac` alias, macOS, Codex, and `browser_open`. The future US work-isolated node, arbitrary commands, remote chat execution, git synchronization and credential replication are outside this slice.

The host owns execution targets, job state, authenticated API, CLI, worker transport and completion receipts. The UI-only Machine module consumes host endpoints without a backend contract change. Deploy the additive host schema and host implementation before publishing that module.

## Submission and authority

`y remote-job target add mac` registers the existing alias. It does not provision SSH or copy a key. `y remote-job submit --target mac --fresh-post` requests the first fresh post from `https://www.xiaohongshu.com/explore`; `--url` instead takes one HTTPS URL on exactly xiaohongshu.com, www.xiaohongshu.com, xhslink.com or www.xhslink.com. Userinfo, control characters, backslashes and non-443 ports are rejected. The two input modes are mutually exclusive. No caller-supplied prompt is accepted.

The authenticated account owns every target and job. API results omit internal IDs and runner tokens. Traced submissions require an owner-bound callback chat on the same trace. The CLI inherits Y_TRACE_ID and Y_CHAT_ID. Untraced UI submissions can omit the callback. Callback messages contain the job ID and terminal state, not page content or secrets.

A queued job is sent on the existing SQS queue. The worker starts `y remote-job run <uuid>` in EC2 tmux. Only one API claim can move queued to dispatched, under the owner-scoped row lock. The claim returns a unique attempt token and private payload to that winner. Heartbeat and finish require that token and attempt. No automatic attempt restart exists. A persistent Mac job directory created with exclusive mkdir prevents a second launch even after its session exits.

## Remote execution

The EC2 stages a fixed stdlib supervisor and bounded input into `~/y-jobs/<uuid>/`. No host credentials are staged. Mac Codex uses its own authentication and existing Chrome extension/app-server. Invocation uses `codex exec --ephemeral --skip-git-repo-check --approve-for-me -C <dir> --json`. `--approve-for-me` already selects the workspace-write sandbox; a separate `--sandbox` flag is rejected by codex-cli 0.159.3. Approval bypass and danger-full-access are not used. The remote tmux socket is `yj`.

The fixed prompt requests navigation and a screenshot, prohibits typing, login, posting, comments, likes, follows, purchases and setting changes, and treats page content as untrusted. **These are model instructions, not an enforceable browser permission boundary.** Server URL validation restricts initial input only; it does not constrain redirects, generated browser actions or extension privileges. The real Chrome account remains exposed to the executor's browser capabilities. No claim of browser-enforced read-only access is made.

The remote supervisor starts Codex in a process group, drains bounded log captures, enforces the independent 180-second default / 600-second maximum timeout, and handles a cancellation marker. It signals the process group and checks that it has disappeared before recording confirmed cancellation or timeout. Losing SSH never proves termination. The browser/app-server itself is pre-existing and is not killed; browser requests already sent may have effects after the Codex process ends.

## State, result and recovery

States: queued, dispatched, running, completed, failed, cancelled, timeout, host_offline. Running requires confirmation of the Mac session or a fast completed exit file. Completed requires exit code zero. Terminal writes are first-wins; stale tokens cannot alter state. Queued cancellation needs no process termination. Active cancellation is a request until the remote supervisor confirms termination.

The runner probes every five seconds within a bounded deadline. Three failed SSH probes, an unconfirmed termination, or a missing exit at the deadline result in terminal host_offline. This is limited v1 recovery, not proof the remote stopped. The independent remote timeout survives EC2 or SSH loss. `y remote-job reap` marks dispatched/running jobs with a heartbeat older than 15 minutes host_offline without relaunching or claiming cancellation. Inspect the remote process and task directory before resubmitting. Automatic stale-run recovery is not included.

A terminal write inserts an immediate `chat_wakeup` outbox receipt in the same database transaction. The existing scheduled delivery pass accepts it with a stable event ID, preserving exactly-once message append across retry and at-least-once broker delivery. This is event completion, not an agent timer or agent polling. A dead originating chat or dispatch refusal remains visible through the receipt. No callback exists for an untraced job.

Report views redact xsec_token values, sk-style keys, JWT-shaped values and credential-labelled fields. Raw payload is returned only to the winning runner. Remote private task files may contain tokenized URLs and are retained in v1. Redaction is heuristic, not a proof that arbitrary page content contains no private data. Screenshots may contain visible account/page information and stay local under `/Users/roy/luohy15/assets/screenshots/remote-job-<uuid>.jpg`; they are not published automatically. Logs/result are bounded at 64KB and screenshots at 10MB.

## HTTP contract

- GET/POST `/api/remote-jobs/targets`: list or upsert the fixed Mac capability.
- POST `/api/remote-jobs`: target, executor (codex), operation (browser_open), payload, timeout_seconds, optional todo_id/trace_id/callback_chat_id. Returns a redacted job record.
- GET `/api/remote-jobs?limit=50`: newest first, maximum 100.
- GET `/api/remote-jobs/{job_id}` and `/result`: redacted record including result, artifacts and diagnostics.
- POST `/api/remote-jobs/{job_id}/cancel`: request cancellation, terminal no-op.
- POST `/api/remote-jobs/{job_id}/claim`: private winner-only runner snapshot, null for duplicate claim.
- POST `/api/remote-jobs/{job_id}/heartbeat`: attempt, claim_token, state.
- POST `/api/remote-jobs/{job_id}/finish`: attempt, claim_token, terminal state, exit_code, termination_confirmed, bounded result/log/artifact fields.
- POST `/api/remote-jobs/reap`: limited stale-run terminalization.

Unknown targets return HostNotConfigured (404). Unsupported capabilities and malformed inputs reject before row creation (422). This slice requires the configured SQS queue. A reported enqueue failure terminalizes an unclaimed row; an ambiguous broker acknowledgement does not lead to another execution attempt.

## Acceptance

Offline checks cover URL rejection, owner-scoped locking shape, duplicate claims, fencing, terminal idempotence and callback insertion, cancellation confirmation, bounded transport construction, runner outcome handling, redaction and route/CLI registration. Real transaction concurrency, Mac behavior and outbox delivery require deployed verification, not a local database test.

After host deployment and module publication, submit one fresh-post job with a same-trace callback. Wait for the real callback, not agent polling. Verify completed/exit zero, a live post title and a JPEG artifact, and ask Roy to confirm the Mac Chrome tab and absence of account mutations. Separately verify queued and running cancellation, remote process-group termination and duplicate-delivery behavior. The earlier Mac probe is prerequisite evidence only, not feature acceptance.
