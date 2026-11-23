---
title: WeChat direct-message channel
type: prd
project: y-agent
feature: wechat-channel
status: active
---

# WeChat direct-message channel

## Problem Statement

WeChat is Roy's and Wu's primary messenger, while y-agent's automatic mobile
surface is Telegram. Roy wants to reach the same y-agent assistant from a normal
WeChat direct message, and later let Wu do the same with her own account, without
sharing sessions, workspace, tools or credentials between users. WeChat has no
general-purpose bot API for personal accounts, so the channel needs a supported,
durable integration rather than browser automation or an unofficial-account
hack.

The first usable version binds Roy's own WeChat to his existing y-agent account,
exchanges text messages with the same manager conversation he uses elsewhere, and
keeps Telegram working unchanged. Wu's onboarding is a later delivery on the same
channel once her allowlisted account exists.

## Solution

Add a host-owned WeChat channel beside Telegram. Tencent publishes the
`@tencent-weixin/openclaw-weixin` channel plugin (MIT, npm `latest` 2.4.10) and a
protocol document addressed to "developers implementing or integrating a
compatible backend". The channel speaks that documented Weixin ClawBot protocol
against `https://ilinkai.weixin.qq.com`:

- QR login binds one Weixin ClawBot identity and returns `bot_token`,
  `ilink_bot_id`, `baseurl` and the scanning account's `ilink_user_id`.
- `POST /ilink/bot/getupdates` long-polls inbound direct messages with a cursor.
- `POST /ilink/bot/sendmessage` replies with the `context_token` from the
  inbound message.
- Direct chats only; groups are not part of the capability.

One ClawBot account can serve several WeChat peers. Each peer is bound to one
existing, admitted y-agent user, so Wu can later attach her WeChat to an account
she created through the normal allowlist flow without a second bot or a second
integration.

A small long-running bridge process holds the poll, and y-agent's API keeps the
chat, admission, isolation and delivery logic, the same division Telegram uses.
`WeClaw` (`fastclaw-ai/weclaw`, MIT) is a reference implementation of the same
protocol; it is not a dependency and does not run any agent for this design.

## User Stories

1. As Roy, I want to bind my own WeChat to my existing y-agent account, so that
   my WeChat conversation reaches the same assistant I already use.
2. As Roy, I want to bind the account already signed in to my CLI by
   scanning one QR code, so that onboarding needs no web UI.
3. As Roy, I want the QR binding to require a fresh one-time code sent from the
   WeChat side, so that a forwarded or leaked QR cannot attach a stranger.
4. As Roy, I want the binding to target an existing, admitted user rather than
   create an account implicitly, so that admission stays the single gate for who
   may use y-agent.
5. As Wu, after my account is admitted, I want to attach my WeChat to it without
   sharing a bot with someone else's identity, so that my conversations are
   unmistakably mine.
6. As Wu, I want messages from my WeChat to land in my own manager chat, so that
   my threads, todos and files stay separate from Roy's.
7. As a user, I want to send ordinary text and get a readable reply in the same
   WeChat conversation.
8. As a user, I want conversation continuity across agent turns, bridge restarts
   and process restarts.
9. As a user, I want long answers split into readable WeChat messages instead of
   raw markdown or a wall of code fences.
10. As a user, I want `/new` or `/clear` to restart the conversation, so that old
    context does not follow me forever.
11. As Roy, I want a sender that is not a bound peer to be refused, so that
    finding the bot does not grant access.
12. As Roy, I want the bot token, context tokens and queued message bodies
    protected by the existing tenant encryption path when the owner is active,
    and never printed in logs or command output.
13. As Roy, I want the bridge to restart without losing the poll cursor or
    duplicating messages, so that I see no gaps or double replies.
14. As Roy, I want a bounded outbound queue, so that a WeChat outage or an
    expired context token does not lose a reply.
15. As Roy, I want y-agent-initiated messages (finished work, reminders) to reach
    me over WeChat on a best-effort basis, queued until my next message refreshes
    the context.
16. As Roy, I want WeChat delivery to happen only for turns triggered from
    WeChat, while my existing Telegram mirroring keeps working exactly as it
    does today.
17. As Roy, I want an operator status command showing binding state, last poll
    time and last delivery error, so that I can diagnose without reading message
    bodies.
18. As Roy, I want to unbind or revoke a peer, so that a lost or replaced phone
    can be cut off.
19. As Roy, I want the channel to make no end-to-end-encryption claim, and to
    state plainly what the operator and the model provider can still read.
20. As the operator, I want the bridge to authenticate to the API with a
    per-account token, so that it never needs database access or tenant keys.

## Implementation Decisions

### Protocol ownership and version

The channel is a native Python client of the documented Weixin ClawBot protocol.
It does not install OpenClaw or run WeClaw's agent loop. We depend on the public
protocol document and the package's request shapes, not on Tencent's plugin
internals. `channel_version` in `base_info` is y-agent's own three-number version
with a suffix, for example `3.0.1/y-agent-1.0.0`, so the backend can identify the
client without pretending to be OpenClaw.

### Components

- **Bridge daemon** (`y wechat bridge --bot default`): runs as `ubuntu` on the
  always-on relay host `claude-relay` under the systemd unit
  `y-agent-wechat-bridge.service`. It holds one long poll per ClawBot account,
  persists `get_updates_buf` and context tokens locally with mode 0600, sends
  outbound rows, and talks to the API only over HTTPS with the account's bridge
  token.
- **API channel routes**: a route group that bypasses the user-JWT middleware and
  authenticates with the bridge token, analogous to the MCP launch gateway. It
  exposes inbound delivery and outbound read/ack, and never returns another
  user's data.
- **Storage**: `wechat_account` (bot identity, encrypted bot token, bridge token
  hash, status), `wechat_peer` (account, provider peer id, bound user id,
  binding state, timestamps), `wechat_context` (account and peer to the latest
  `context_token`), `wechat_outbox` (pending reply, attempts, outcome) and an
  inbound dedupe record keyed by account and provider message id.
- **Delivery hook**: the worker's manager reply path gains a WeChat branch beside
  the Telegram branch. It enqueues an outbox row instead of sending inline,
  because only the bridge holds the bot token and context tokens.

### Binding

1. Roy runs `y wechat login` on the default node. It binds only the y-agent
   account signed in there with `y login`; there is no email override. Without
   a valid saved login, the command tells him to run `y login` before showing
   a QR code. The API uses the authenticated identity and requires the admitted
   maintainer for this first version.
2. The command starts a short-lived binding session and writes a PNG of the
   QR from `qrcode_img_content` to `~/.y-agent/wechat/<bot>.png` (mode `0600`).
   It prints that absolute path and does not render a terminal QR. Roy opens
   the file, scans it, and the command polls the QR status. After the scan is
   confirmed it removes the PNG, then prints a fresh six-digit code. If WeChat
   asks for a PIN, the operator enters it in the terminal.
3. The scanner's `ilink_user_id` is recorded against the target user, but the
   peer stays `pending` until that WeChat account sends the six-digit code as its
   first message within ten minutes. A QR scanned by someone else therefore
   cannot complete the binding.
4. On success the peer becomes `active` and later messages are accepted only
   from that peer id. `binded_redirect` means the ClawBot is already bound
   elsewhere; the flow stops with an explicit message instead of reusing
   credentials.
5. A second user's binding is outside this version. It cannot be initiated by
   naming that user from Roy's CLI session.

Binding sessions are single-use. Expiry, cancellation and a second scan
invalidate them. `y wechat unbind` moves a peer to `revoked`, and revoking the
last peer stops the bot's poll. Rebinding is a new login flow.

### Message flow

Inbound:

1. The bridge posts each non-bot `WeixinMessage` to the API with account id,
   provider message id, sender id, text and the message's `context_token`.
2. The API rejects unknown, revoked or paused accounts, refuses a sender that is
   not an active peer, re-checks admission for the bound user, and deduplicates
   by provider message id before touching chat.
3. Non-text items receive one fixed "text only for now" notice and create no
   turn. Quoted text is prepended as a blockquote in the same shape Telegram
   uses.
4. The text reaches the bound user's manager chat through the existing
   append-or-steer path with `source="wechat"` and `human_reply=True`; a new
   manager chat is created when none exists. `/new` and `/clear` restart that
   manager session, mirroring Telegram.

Outbound:

1. A manager reply is enqueued when the turn was triggered by a WeChat user
   message. Explicit proactive delivery from routines or completed work uses the
   same queue when the [notify gateway](notify-gateway.md) selects WeChat.
2. The bridge reads the queue, sends `sendmessage` with the peer's latest
   `context_token`, and acks the result. A missing or expired token leaves the
   row `blocked_on_context`; it is delivered after the next inbound message
   refreshes the token. Failures retry with bounded backoff and then become a
   visible operator error, never an unbounded loop.
3. Markdown becomes WeChat-readable plain text: code fences and markup removed,
   links reduced to display text, artifact fences reduced to the same
   placeholders Telegram uses. Long messages are split with an explicit
   continuation marker.

Telegram delivery stays role-based and unchanged: Roy's manager replies continue
to mirror to Telegram. A WeChat-triggered turn therefore appears in both
surfaces, matching how a web-triggered manager turn already behaves.

### Isolation and deployment

- Each peer belongs to exactly one user; account and peer resolution are
  owner-scoped and fail closed.
- QR login stays on the default node. To move polling to the relay host,
  stop the old bridge, copy its final state (including the poll cursor) to
  `/home/ubuntu/.y-agent/wechat/default.json` (owner `ubuntu`, mode `0600`),
  then enable and start the relay service. Never run both pollers at once.
- The relay hosts the bridge, not a dedicated user execution environment.
  Wu's dedicated node, separate `bot_config`, separate work directory and
  separate credentials are a later delivery; a shared node is not acceptable as
  isolation once a second user is live, because her shell tools could read the
  operator's files.
- The bridge stores only the bot credentials, peer context tokens and its
  bridge token. It has no database URL and no tenant master key.
- A per-peer inbound rate cap and a bounded outbox prevent runaway loops between
  the assistant and WeChat.
- Logs carry account, peer and message ids and outcomes, never message bodies,
  tokens or QR payloads.

### Encryption

The channel adds no new cryptography. Its new classified fields register in the
existing classification registry (`bot_token`, context tokens, queued text) and
are sealed and opened by the existing flush/load hooks when the owning user is
tenant-encryption-active. Chat rows are already classified there. Encryption
eligibility and activation remain the existing hosted-tenant rollout
(`docs/prd/hosted-tenant-confidentiality.md`); this feature neither changes
eligibility nor claims coverage for an inactive owner. Roy's personal account is
not currently encryption-active, so his channel data is plaintext at rest and
readable from database copies. This is not E2EE: the execution node, relay,
provider and a process holding the master key can read plaintext.

## Testing Decisions

Verification targets external behavior at the channel boundary:

- A deterministic local stub of the iLink HTTP API exercises QR states (`wait`,
  `scaned`, `confirmed`, `expired`, `need_verifycode`, `binded_redirect`), cursor
  persistence across a simulated restart, duplicate `message_id` delivery,
  unbound-sender refusal, outbox retry and `blocked_on_context` recovery.
- Chat-level checks assert that a WeChat message creates or steers the intended
  manager chat, that a reply enqueues exactly one outbox row, and that a
  Telegram-triggered turn creates none.
- Security checks assert that a peer cannot read another peer's outbox or bind
  state through the bridge routes, that an unadmitted user cannot bind, and
  that logs contain no token or message body.
- The live gate needs one real WeChat account and a QR scan: bind Roy's account,
  send the code, exchange two turns, restart the bridge, exchange a third turn,
  and confirm continuity without duplicate replies. The delivery records exactly
  which steps need the phone and what stays unverified if it is unavailable.

## Out of Scope

- Wu's onboarding and the dedicated execution node, separate credentials and
  separate work directory she will require. The channel supports binding an
  existing admitted user; provisioning that user is a later todo.
- Self-serve binding from the web UI; the first version starts from the
  operator's CLI.
- WeChat group chats; the ClawBot capability declares direct chats only.
- Images, voice, files and video in either direction, beyond a fixed text notice
  for inbound media.
- The WeChat Official Account and WeCom (企业微信) surfaces.
- More than one ClawBot account per deployment or more than one peer per user.
- End-to-end encryption, and any claim that the operator cannot read content.
- Changing tenant-encryption eligibility, key custody or activation.
- Billing, quotas and cost controls for model usage.
- Streaming, message editing and typing indicators in WeChat.
- Generalizing Telegram and WeChat into a shared multi-channel framework; the
  first version keeps the channel-specific slice.
