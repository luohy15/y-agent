# Lambda Detached Process Management

Worker Lambda manages long-running Claude Code processes on EC2 without being limited by Lambda's 15-minute timeout.

## Problem

- Lambda max timeout is 900s (15 min), but Claude Code tasks can run much longer
- SSH channel ties process lifecycle to Lambda — when Lambda times out, SSH disconnects and the remote process dies
- One Lambda per task is wasteful when event frequency is low

## Solution

Decouple process execution from Lambda lifecycle by running Claude Code in **tmux detached sessions** on EC2, with Lambda acting as a lightweight monitoring layer.

```
SQS message → Lambda Worker
  Phase 1: Start tmux detached process on EC2 + register in DynamoDB
  Phase 2: Event loop — tail stdout, poll for new processes, handle deadlines
```

## Architecture

### Process Lifecycle

```
Start:   Lambda SSH → tmux new-session -d → claude -p < stdin > stdout
Monitor: Lambda SSH → tail -f stdout → parse stream-json → write DB
Pause:   Lambda deadline → save offset to DynamoDB → send SQS continuation
Resume:  New Lambda → read offset from DynamoDB → tail -n +{offset} -f stdout
Done:    Detect .exit file → post_hooks → cleanup DynamoDB
```

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| Process Manager | `worker/src/worker/process_manager.py` | DynamoDB CRUD for process state, lease acquire/renew |
| Detached SSH Start | `agent/src/agent/claude_code.py` `start_detached_ssh()` | SFTP stdin, tmux launch, stdout/stderr redirect |
| Detached SSH Tail | `agent/src/agent/claude_code.py` `tail_ssh_output()` | tail -f stdout, stream-json parsing, deadline/interrupt |
| SSH Pool | `agent/src/agent/ssh_pool.py` | Connection reuse per (host, port, user) |
| Event Loop | `worker/handler.py` `_monitor_loop()` | Poll DynamoDB, acquire leases, manage tail tasks |
| Runner Entry | `worker/src/worker/runner.py` `run_chat()` | Routes to detached vs inline based on bot/vm config |

### EC2 File Layout

```
/tmp/cc-{chat_id}.stdin    # prompt (written via SFTP)
/tmp/cc-{chat_id}.stdout   # stream-json output (tail target)
/tmp/cc-{chat_id}.stderr   # error output
/tmp/cc-{chat_id}.exit     # exit code (signals process completion)
```

tmux session name: `cc-{chat_id}`

### DynamoDB Record

```json
{
  "id": "proc-{chat_id}",
  "chat_id": "abc123",
  "user_id": 1,
  "vm_name": "ssh:user@host:22",
  "status": "running",
  "stdout_offset": 1234,
  "session_id": "claude-session-id",
  "last_message_id": "msg-xxx",
  "monitor_owner": "lambda-request-id",
  "monitor_lease": 1712001800,
  "ttl": 1712086400
}
```

## Routing Logic

`run_chat()` decides detached vs inline after resolving config:

```
bot_config.api_type == "claude_code"
  AND vm_config.vm_name.startswith("ssh:")
  AND vm_config "detach" feature flag exists for user
→ detached mode
```

Everything else → inline (original `_run_claude_ssh` / `run_agent_loop`).

## Feature Flag

Detached mode is gated by a `vm_config` row with `name=detach` for the user. This allows safe rollout and instant rollback (delete the row to revert to inline mode).

## Event Loop

The Lambda handler runs a two-phase architecture:

**Phase 1** processes SQS records — starts new tmux processes (fast, seconds) or runs non-SSH tasks inline.

**Phase 2** enters a polling event loop:
- Every 10s: scan DynamoDB for unleased running processes, acquire leases, start tail coroutines
- Completed processes: run post_hooks, send Telegram, update chat, cleanup DynamoDB
- Idle 30s with no processes: exit (scale to 0)
- Lambda deadline approaching: wait for tails to finish naturally (via `check_deadline_fn`), save offsets, send SQS continuation message

## Scaling

| Scenario | Lambda Count | Behavior |
|----------|-------------|----------|
| No tasks | 0 | All Lambdas idle-exit |
| 1-100 processes | 1 | Single Lambda event loop manages all |
| 100+ processes | 2+ | Lease mechanism prevents conflicts |
| New task, Lambda has capacity | unchanged | Running Lambda discovers via DynamoDB poll |
| New task, all Lambdas full | +1 | SQS triggers new Lambda |

Per-process overhead on Lambda: ~1MB (SSH channel + stream parser). One Lambda (1024MB) can comfortably monitor 100 processes.

## SSH Connection Pool

`SSHPool` reuses SSH connections per (host, port, user). Multiple processes on the same EC2 share one connection (SSH multiplexes channels). Auto-detects stale connections and reconnects.

## SAM Configuration

```yaml
WorkerFunction:
  Events:
    SQSTrigger:
      Type: SQS
      Properties:
        BatchSize: 10
        MaximumBatchingWindowInSeconds: 5
        FunctionResponseTypes:
          - ReportBatchItemFailures
```

## Commits

1. `993dff2` — Phase A: BatchSize 10, asyncio.gather, partial batch failure
2. `993dff2` — Phase B: tmux detached, DynamoDB, event loop, continuation
3. `456dc68` — Phase C: SSH connection pool
4. `dc6741a` — Bugfix: routing, tail leak, offset save
5. `86c63bb` — Bugfix: use resolved vm_name
6. `af8053e` — Bugfix: cleanup before stdin write
7. `2e57550` — Bugfix: zsh glob compatibility
