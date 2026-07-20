# PRD Index

One entry per PRD in this directory. Before writing a new PRD, scan this
index for overlapping scope: extend the existing PRD instead of creating a
near-duplicate.

| PRD | Scope |
|-----|-------|
| [bot-routing](bot-routing.md) | Routes each dispatched session to a bot via unified filters (bot name, backend, tier) intersected over the config pool: one candidate is used directly, several are weighted-drawn, and no filters or an empty result falls back to tier2 (never a skill-derived tier); a documented tier-role policy (tier2 default, tier1 judgment work, tier0 user escalation only, tier3 cheap volume) governs tier requests. |
| [bot-usage](bot-usage.md) | Owns bot-page usage visibility: durable per-model spend analytics plus current Claude and GPT (Codex) subscription status for the rolling 5-hour and 1-week limit windows. |
| [chat-core](chat-core.md) | Owns the durable chat conversation model and its lifecycle across all surfaces: GUI chat list/detail/send, CLI dispatch (`y chat -m` fire-and-forget vs `--wait`) and REPL, and the persist-enqueue-run-stream pipeline (API → queue → worker → backend subprocess → message stream). |
| [chat-steer](chat-steer.md) | Delivers user messages sent to a chat mid-turn into the already-running agent session exactly once, without spawning a duplicate worker, across backends that accept live input and those that must be killed and resumed. |
| [cli-file-transfer](cli-file-transfer.md) | Owns bidirectional Mac↔EC2 file transfer in the `y` CLI under `y file upload` / `y file download`: rsync over SSH, API default-host resolution, dry-run/mirror/checksum/exclude, no personal inventory in the public surface. |
