# PRD Index

One entry per PRD in this directory. Before writing a new PRD, scan this
index for overlapping scope: extend the existing PRD instead of creating a
near-duplicate.

| PRD | Scope |
|-----|-------|
| [bot-dispatch-tier-routing](bot-dispatch-tier-routing.md) | Routes each dispatched session to a bot by capability tier: bots carry a tier as data, dispatchers request a tier instead of a name, explicit bot/backend pins bypass routing, and a documented policy governs which work deserves the strong tiers. |
| [chat-core](chat-core.md) | Owns the durable chat conversation model and its lifecycle across all surfaces: GUI chat list/detail/send, CLI dispatch (`y chat -m` fire-and-forget vs `--wait`) and REPL, and the persist-enqueue-run-stream pipeline (API → queue → worker → backend subprocess → message stream). |
| [steer](steer.md) | Delivers user messages sent to a chat mid-turn into the already-running agent session exactly once, without spawning a duplicate worker, across backends that accept live input and those that must be killed and resumed. |
| [usage-tracking](usage-tracking.md) | Persists a per-model daily LLM spend time series (tokens/cost/requests) synced from the relay into y-agent's own database, past the relay's retention window, and exposes it via a usage API and bot-page charts. |
