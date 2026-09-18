---
title: Session Tree Recovery
type: prd
project: y-agent
feature: session-tree-recovery
status: active
---

# Session Tree Recovery

## Problem Statement

Work in y-agent runs as a tree of agent sessions: a parent session dispatches a
subtask with `y chat` and then stops at a natural boundary, because the
coordination model forbids polling a child. The tree only keeps moving when the
child eventually sends a callback into the parent's chat. That callback is
in-band prose sent by a model, over a best-effort HTTP call, with no durable
record that the handoff ever happened.

So a single lost message silently freezes an entire branch. The observed
failure modes:

- The child finished the work but never called back (it judged a callback
  unnecessary, ran out of context, or simply forgot), and the parent waits
  forever for a message that will never arrive.
- The child tried to call back but the call failed (API error, network blip,
  rejected target), the CLI printed an error the model had already stopped
  reading, and the callback is gone.
- The child called back to the wrong place: a stale `from_chat` from another
  trace, a topic address that resumed some other todo's chat, or a callback
  aimed at a root topic that the API correctly refuses. The parent still waits,
  and a foreign chat may now hold a message about a task it is not running.
- The child's run failed outright (launch error, hard timeout, backend error).
  The chat shows an error, but nothing tells the parent, so the branch stalls
  the same way as a lost callback.

Because nothing persists the parent → child edge, none of these are
distinguishable from "the child is still working". The only current detector is
Roy noticing hours later that a todo went quiet, then reading chat transcripts to
reconstruct who was waiting on whom. Recovery is manual, and the recovery action
itself (re-dispatching a subtask that may have already run) risks duplicating
side effects: a second commit, a second deploy, a second finished todo.

## Solution

Make the handoff a durable, first-class record instead of an in-band message.

Every dispatch that has a parent (a `from_chat`) writes a **dispatch edge**: a
persisted row naming the trace, the parent chat, the child chat, and the state
of the handoff. A callback is what *closes* that edge, and the API recognises it
structurally rather than by prose. With the edge persisted, the system can
finally tell apart the states that look identical in a transcript: still
running, blocked on Roy, blocked on its own children, finished without calling
back, failed, or delivered to the wrong parent.

A scheduled server-side sweeper (not a session, not a poll) periodically
evaluates open edges. When an edge is provably done-but-unclosed, the system
synthesizes exactly one callback into the recorded parent chat, so the parent
resumes with a truthful message pointing at the child chat and its outcome.
When the situation is ambiguous or already escalated once, the system stops and
raises it to Roy instead of guessing.

Callbacks that fail ownership validation (wrong trace, wrong parent, cross-user)
are never delivered and never silently dropped: they are quarantined as visible
rows with the reason, and an operator can re-route or discard them.

The system never re-runs a child's work to recover from a stall. Recovery moves
*information* up the tree; only Roy (or a parent session acting on the report)
decides whether the work itself should run again. The one existing automatic
re-run (the single resume-on-5xx retry) stays exactly as it is and is not
extended by this feature.

## User Stories

### Durable handoff record

1. As a parent session, I want each dispatch I send with a `from_chat` to
   create a durable edge naming (trace, parent chat, child chat), so that the
   handoff exists as data rather than only as text in two transcripts.
2. As a parent session, I want the edge to record which of my messages produced
   it and which chat it targeted, so that a recovery message can be attributed
   to a specific dispatch rather than to a topic.
3. As a dispatcher, I want an edge created whether the dispatch created a new
   child chat, resumed the trace's existing chat for that topic, or appended to
   a running child, so that no dispatch shape is invisible to recovery.
4. As a dispatcher, I want dispatches with no parent (a human sending from the
   web UI, a routine firing, a root-topic conversation) to create no edge, so
   that recovery only ever fires where something is genuinely waiting.
5. As a parent session, I want the edge to default to expecting a callback, so
   that the failure the feature exists to catch (a callback that never comes) is
   detected by default rather than opted into.
6. As a dispatching session, I want an explicit way to declare a dispatch
   fire-and-forget, so that a deliberately callback-free dispatch is recorded as
   closed-by-design and never produces a recovery message.
7. As a child session, I want my callback to close the edge automatically when
   it lands in the recorded parent chat under the same trace, so that correct
   behaviour requires no new command and no extra step.
8. As an operator, I want an edge to carry its own public id, so that I can
   name one specific handoff in a CLI command without ambiguity.

### Distinguishing the states

9. As an operator, I want the system to classify an open edge into exactly one
   state from evidence it already holds (the child chat's running flag,
   completion predicate, error status, attention flag, and the child's own open
   outbound edges), so that "stalled" means something precise instead of "quiet
   for a while".
10. As an operator, I want a child that is still running to be classified as
    `running` and left completely alone, so that recovery never interrupts live
    work.
11. As an operator, I want a child that completed a turn while flagged
    `needs_attention` to be classified as blocked on me, not stalled, so that a
    session waiting for my answer is never "recovered" with a synthesized
    callback that hides the question.
12. As an operator, I want a child that is idle but still has its own open
    outbound edges to be classified as waiting on its children, so that a
    coordinator legitimately parked between sub-dispatches is not mistaken for a
    dead branch.
13. As an operator, I want a child that is idle, unflagged, has no open
    outbound edges, and produced no callback to be classified as
    `completed_without_callback`, so that the most common real failure is named
    exactly.
14. As an operator, I want a child whose last run ended in an execution error
    (launch failure, backend error, hard timeout) to be classified as `failed`
    rather than lumped in with a missing callback, so that the report the parent
    receives is truthful about what happened.
15. As an operator, I want a child chat still marked running with no live
    process behind it to be classified as `stalled`, so that a lost worker is
    distinguishable from a slow one.
16. As an operator, I want the classifier to be pure and side-effect-free, so
    that I can ask "what does the system think is happening on this trace?"
    without changing anything.

### Recovery

17. As a parent session, I want the system to deliver at most one synthesized
    callback per edge, into the exact recorded parent chat id, so that a stalled
    branch resumes without any chance of waking the wrong conversation.
18. As a parent session, I want the synthesized callback to state plainly that
    it was generated by recovery, name the child chat and its observed outcome,
    and tell me to verify state before acting, so that I do not treat a machine
    report as the child's own verified result.
19. As a parent session, I want the synthesized callback to carry the same trace
    metadata prefix a real callback carries, so that my existing trace-hygiene
    checks still apply to it.
20. As an operator, I want recovery to never re-dispatch or re-run the child's
    task, so that a recovery pass can never produce a second commit, deploy, or
    finished todo.
21. As an operator, I want recovery to never change a todo's status or write
    todo progress on the child's behalf, so that no automated path can complete
    the wrong todo.
22. As an operator, I want a bounded escalation ladder per edge (one synthesized
    callback, then one Telegram escalation to me, then no further automatic
    action), so that a permanently broken branch produces two messages, not an
    unbounded stream.
23. As an operator, I want a grace window between the child going idle and the
    edge being declared unclosed, so that a callback in flight is never
    duplicated by a racing recovery pass.
24. As an operator, I want recovery attempts, timestamps, and the resulting
    state persisted on the edge, so that the escalation ladder survives a
    process restart and cannot reset itself into a loop.
25. As an operator, I want an edge whose parent chat has since been deleted or
    is otherwise undeliverable to escalate to me directly instead of failing
    silently, so that no branch is lost because its parent went away.

### Wrong parent, wrong trace, quarantine

26. As a user, I want a callback whose declared trace conflicts with the trace
    persisted on the sender's chat to be rejected at accept time with an
    explicit error, so that a stale `--trace-id` cannot inject one trace's
    result into another's conversation.
27. As a user, I want a callback addressed to a chat that is not the sender's
    recorded parent and shares no trace with it to be rejected rather than
    appended, so that a hallucinated or stale `from_chat` cannot overwrite an
    unrelated conversation's context.
28. As a user, I want every rejected callback preserved as a quarantine record
    with its full message, sender, intended target, and rejection reason, so
    that a wrongly addressed result is recoverable instead of destroyed.
29. As an operator, I want to list quarantined callbacks and either deliver one
    to a chat I name explicitly or discard it, so that I have a manual path out
    of every ambiguous case.
30. As an operator, I want a quarantined callback to never be delivered
    automatically, so that the system's guess never substitutes for my judgment
    on a message it already found suspicious.
31. As a user, I want the existing root-topic callback rejection preserved, and
    its rejected message quarantined like any other, so that an accidental
    callback to `manager` is visible rather than merely refused.
32. As a user, I want all edge and quarantine reads and writes scoped to the
    owning user, so that a public chat id colliding across accounts can never
    cross an ownership boundary.

### Delivery reliability

33. As a child session, I want a failed callback (network error or server-side
    5xx) retried a bounded number of times with backoff inside the same CLI
    invocation, so that a transient blip does not cost a whole branch.
34. As a child session, I want each callback to carry an idempotency key so a
    retried delivery appends the message exactly once, so that bounded retry can
    never double-post a result.
35. As a child session, I want a rejected callback (4xx) to fail immediately
    with a clear error rather than be retried, so that a wrong address is
    corrected rather than hammered.
36. As a child session, I want the CLI to exit nonzero and print an actionable
    message when a callback is ultimately undeliverable, so that I can still
    report the failure in my own chat before I stop.
37. As an operator, I want an undeliverable callback to degrade into exactly the
    same missing-callback path the sweeper already handles, so that there is one
    recovery mechanism rather than a separate client-side spool to maintain.

### Observability and operator control

38. As an operator, I want to list dispatch edges filtered by trace, state, or
    age, so that I can answer "what is this trace waiting on?" in one command.
39. As an operator, I want each listed edge to show parent chat, child chat,
    topic, state, age, and recovery attempts, so that I can judge a stalled
    branch without opening transcripts.
40. As an operator, I want to force recovery on one named edge, so that I can
    unblock a parent immediately rather than waiting for the next sweep.
41. As an operator, I want to dismiss an edge as resolved-by-hand, so that work
    I completed manually stops generating escalations.
42. As an operator, I want the sweeper to log every classification and action
    with the edge id, so that after an incident I can reconstruct what the
    system decided and why.
43. As an operator, I want a sweep pass to be safe to run repeatedly and
    concurrently without duplicating deliveries, so that an overlapping schedule
    or a manual run is harmless.
44. As an operator, I want the sweeper to be a scheduled server-side job, never
    a session watching another session, so that the no-poll coordination model
    is preserved exactly as it is today.

## Implementation Decisions

### The edge is the new durable state

- **New kernel table `dispatch_edge`.** Dispatch is host runtime (like `chat`
  and `bot_config`), so the edge is a host-owned kernel table, not a module
  table. Shape:

  | Column | Meaning |
  |--------|---------|
  | `id` | internal PK |
  | `user_id` | owner (every query filters on it) |
  | `edge_id` | public 6-hex id, the operator-facing handle |
  | `trace_id` | the dispatch's trace (todo id), nullable |
  | `parent_chat_id` / `parent_topic` | the recorded return address |
  | `child_chat_id` / `child_topic` / `child_skill` | the dispatched target |
  | `dispatch_message_id` | the child message this dispatch appended |
  | `callback_expected` | false only for an explicitly fire-and-forget dispatch |
  | `state` | see the state machine below |
  | `closed_by_message_id` | the callback message that closed it, when closed |
  | `recovery_attempts` / `last_recovery_at` | the bounded escalation ladder |
  | `created_at` / `updated_at` | timing, and the basis for the grace window |

  Uniqueness is on `(user_id, edge_id)`, matching the `chat` precedent that a
  public id is only unique per user. Migration is hand-written SQL under
  `migration/`, applied by the maintainer, per repo convention.

- **Edge creation happens at the notify accept boundary**, in the same
  transaction-shaped step that persists the user message and marks the child
  running. An edge is created when the request carries a `from_chat_id` and that
  chat resolves to a live chat owned by the same user. No `from_chat_id` (web
  send, routine fire, human CLI) means no edge: nothing is waiting.

- **`callback_expected` defaults to true.** The asymmetry is deliberate: an edge
  wrongly expecting a callback costs one synthesized message the parent can
  ignore; an edge wrongly not expecting one costs a permanently frozen branch,
  which is the entire problem being solved. A dispatcher that genuinely wants
  fire-and-forget declares it explicitly, and the edge is created in
  `closed_by_design` so it stays visible in listings without ever being swept.

- **A callback closes its edge structurally.** When a notify request names
  `chat_id == parent_chat_id` from a sender whose chat is the edge's
  `child_chat_id`, under the same trace, the edge moves to `resolved` and
  records the closing message id. This is recognised from the request's routing
  fields, never from parsing the model's prose.

### State machine

```
                       ┌─────────────────────────────────────────┐
  dispatch accepted →  │ open                                    │
                       └──┬──────────────────────────────────────┘
                          │  classified on each sweep (pure, no writes)
     ┌────────────────────┼────────────────────┬───────────────────┐
     ▼                    ▼                    ▼                   ▼
  running          awaiting_user        awaiting_children     (terminal-ish)
 (child live)   (child needs_attention) (child has open        completed_without_callback
     │                    │              outbound edges)        failed
     └────── leave alone ─┴──────────────┴───────────────┐      stalled
                                                          │        │
                          callback lands  ────────────────┼────────┤
                                   ▼                      ▼        ▼
                               resolved            recovery ladder (bounded)
                                                     1. synthesized callback → recovered
                                                     2. Telegram escalation  → escalated
                                                     3. stop
                                                            │
                        operator: y trace dismiss ──────────┴──→ dismissed
```

`quarantined` is a separate record type, not an edge state: a quarantined
callback is a message that was refused, not a handoff that exists.

- **`running`, `awaiting_user`, and `awaiting_children` are suppressors, not
  failures.** They are the three ways a quiet branch is legitimately quiet, and
  each maps to evidence the system already stores: the chat's `running` flag,
  the `needs_attention` flag from the chat-core attention model, and the child's
  own open outbound edges in this same table. The third one is the structural
  payoff of persisting edges at all: without it, every parked coordinator looks
  like a dead branch.

- **`completed_without_callback` requires all suppressors to be false**: the
  child is idle by the shared completion predicate, not `needs_attention`, has
  no open outbound edges, its last run did not error, and the grace window since
  it went idle has elapsed.

- **`failed` covers execution errors** (launch failure, backend error result,
  hard timeout) and is reported upward rather than retried. The existing single
  automatic resume-on-5xx retry inside the monitor is the *only* automatic
  re-run in the system and is untouched by this feature; recovery deliberately
  adds no second retry layer, because a retry that re-runs an agent's work can
  duplicate commits, deploys, and todo mutations.

- **`stalled` is the chat-says-running-but-nothing-is-behind-it case**: no live
  process record or lease for a chat still flagged running. Recovery for a
  stalled edge marks the chat idle (the same correction the launch-failure path
  already performs), then reports upward.

### Recovery mechanics

- **The sweeper is a scheduled admin action**, alongside `check_reminders` and
  `tick_routines` in the admin Lambda, fired by its own EventBridge schedule. A
  server-side scheduled job is the only construct that both preserves the
  no-poll rule (no session watches another session) and survives the death of
  every session involved.

- **Exactly one synthesized callback per edge.** Delivery goes through the same
  notify accept path a real callback uses, targeted by the recorded
  `parent_chat_id` only, never by topic resolution. It carries the standard
  `[trace:... from:... to_chat:...]` prefix so the parent's trace checks apply,
  and its body identifies itself as recovery-generated, names the child chat
  id, states the observed outcome, and instructs the parent to verify state
  before acting. Idempotency is structural: the delivery is attempted only when
  `recovery_attempts == 0`, and the counter is incremented in the same write
  that records the delivery, so a concurrent or repeated sweep cannot double-post.

- **Escalation stops at two.** If the edge is still unresolved on a later sweep
  after a synthesized callback, one Telegram message goes to Roy naming the edge,
  trace, and both chats, and the edge moves to `escalated`. No further automatic
  action follows: a branch that survived both rungs is an ambiguous case, and the
  requirement is an operator-visible path, not an infinitely persistent robot.

- **Grace window before declaring an edge unclosed.** A callback is normally sent
  *during* the child's final turn, so the window only needs to cover the gap
  between the callback landing and the child going idle. It is a configured
  constant (proposed: sweep every 5 minutes, declare after 10 minutes idle),
  chosen so the first automatic action is minutes late rather than hours.

### Accept-time validation and quarantine

- **Two rejection rules, both narrow.** (1) *Trace conflict*: the request's
  `trace_id` differs from the trace persisted on the sender's chat. (2) *Wrong
  parent*: the request targets a chat that is neither the sender's recorded
  parent nor a chat sharing its trace. Both are checked only when both sides
  carry the relevant persisted value, so the existing legitimate shapes survive:
  root chats deliberately hold no trace id, and re-dispatching an existing chat
  under a new trace stays allowed with its current loud warning.

- **Rejection means quarantine, not discard.** A new `dispatch_quarantine`
  record stores the full message, sender chat, intended target, declared trace,
  and reason. The existing root-topic callback rejection keeps its current 400
  and its current error text and additionally quarantines the message. Nothing
  in quarantine is ever delivered automatically; an operator names a target chat
  explicitly to release one.

### Delivery reliability at the client

- **Bounded CLI retry with an idempotency key.** `y chat` retries a callback up
  to 3 attempts with exponential backoff on network errors and 5xx only; 4xx
  fails immediately (a rejection is an addressing bug, not a blip). Each attempt
  carries a client-generated idempotency key; the API records it on the appended
  message and returns the original response for a repeat, so retry cannot
  double-append.

- **No client-side spool.** An ultimately undeliverable callback exits nonzero
  with an actionable message and is otherwise indistinguishable from a callback
  that was never sent, which is exactly the case the sweeper already handles.
  One recovery mechanism, not two.

### Operator surface

- `y trace edges [--trace-id <id>] [--state <state>] [--older-than <duration>]`
  lists edges with parent, child, topic, state, age, and attempts.
- `y trace recover <edge_id>` forces the next rung of the ladder immediately.
- `y trace dismiss <edge_id>` marks an edge resolved by hand.
- `y trace quarantine [list]`, `y trace quarantine deliver <id> --chat-id <id>`,
  `y trace quarantine discard <id>` cover the misrouted-callback path.

These live under the existing built-in `y trace` group (today only `share` /
`unshare`), because recovery must keep working when no module is loadable.

### Open decisions for Roy

- **Sweep cadence and grace window** (proposed 5 min / 10 min) are guesses from
  the shape of typical dispatches, not measurements. Worth confirming against
  real trace timings before the constants are frozen.
- **Whether `escalated` edges should also flip the parent chat's
  `needs_attention` flag** in addition to the Telegram message. It would surface
  stalls in the web UI for free, but it writes to a chat the recovery system does
  not own.
- **Whether the trace waterfall should render edge state**. The CLI is the
  committed operator surface here; a visual badge is an obvious follow-up but
  needs a UI decision that this PRD does not make.

## Testing Decisions

Everything here is a state machine over persisted rows, so the tests are
table-driven over states and evidence rather than transcript fixtures.

- **Classifier tests are the core of the suite**: one table mapping (chat
  running flag, completion predicate result, needs_attention, error status,
  count of open outbound edges, age) to the expected state, with a row per
  suppressor asserting it individually blocks `completed_without_callback`. The
  classifier stays pure so these need no fakes.
- **Edge creation at the notify boundary** extends the existing API-level notify
  suite (stubbed queue): edge created for each dispatch shape (new chat, topic +
  trace resume, append to a running child), no edge without `from_chat_id`, no
  edge for a routine fire, and `closed_by_design` for an explicit
  fire-and-forget dispatch.
- **Callback closes the edge structurally**: a notify from the child to the
  recorded parent under the same trace resolves the edge and records the closing
  message id; a callback with matching routing but different prose still closes
  it (proving no prose parsing).
- **Failure injection is the acceptance criterion**, one focused test per named
  failure class: child completes with no callback, child errors out, child chat
  left running with no process, callback delivery returning 5xx then succeeding,
  callback returning 4xx, callback with a conflicting trace, callback to a
  non-parent chat, callback to a root topic.
- **Idempotency and bounds get explicit assertions**: two consecutive sweeps
  produce one synthesized callback; a third sweep after escalation produces
  nothing; a retried CLI delivery with the same idempotency key appends one
  message; recovery never enqueues a child re-run and never writes a todo (assert
  on the absence of those calls, since these are the duplicate-side-effect
  guarantees the feature exists to hold).
- **Owner scoping** follows the chat-core precedent that caught the same class
  of bug: two rows sharing one public id under different `user_id`s, asserting
  every edge and quarantine read/write touches only the owner's row.
- **Quarantine round-trip**: a rejected callback is listable, deliverable to an
  explicitly named chat, discardable, and never delivered by any automatic path.

## Out of Scope

- **Re-running a child's task.** Recovery moves information, never work. Any
  automatic re-execution of a stalled subtask is explicitly excluded because it
  cannot be made side-effect-safe against commits, deploys, and todo mutations.
- **Extending the existing automatic retry.** The single resume-on-5xx retry in
  the monitor keeps its current scope and its current bound; this feature adds
  no second retry layer around it.
- **Mid-turn message delivery mechanics** (steer claim/drain, kill-and-resume,
  exactly-once into a live session): owned by the chat-steer PRD. This PRD
  assumes a delivered message is a delivered message.
- **Dispatch target resolution, root-topic rejection semantics, chat identity
  immutability, and the notify request contract**: owned by the chat-core PRD.
  This feature adds edge creation and two validation rules at that boundary and
  changes nothing else about resolution. Boundary recorded in both PRDs.
- **Bot and tier selection for a recovered or re-dispatched task**: owned by the
  bot-routing PRD.
- **Context-handoff policy** (when a session should hand off, the reminder
  wording, self-restart vs callback): owned by AGENTS.md and the chat-core
  reminder mechanism. A handing-off session's callback is an ordinary callback
  here.
- **Trace waterfall visualization and public trace shares**: this feature's
  operator surface is the CLI plus one Telegram escalation. A visual edge-state
  badge is a possible follow-up, not part of this scope.
- **Cross-user or multi-tenant recovery**: every path is single-owner scoped.
- **Automatic todo status transitions.** Recovery never finishes, reopens, or
  progresses a todo; it only reports upward so a human or a parent session
  decides.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3166 | Established the durable feature home for session-tree recovery: dispatch edges as persisted parent→child handoff state, a suppressor-based classifier (running / awaiting_user / awaiting_children vs completed_without_callback / failed / stalled), a bounded scheduled recovery ladder (one synthesized callback, then one escalation), accept-time trace/parent validation with quarantine instead of discard, bounded idempotent CLI callback retry, and a `y trace` operator surface. No implementation yet | - | - | - | - | requirements defined; implementation not started |
