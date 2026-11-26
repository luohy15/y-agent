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
WeChat direct message. A second admitted user must also be able to reach their
own assistant from their own WeChat, without sharing sessions, workspace, tools,
credentials or conversation history with Roy. WeChat has no general-purpose bot
API for personal accounts, so the channel needs a supported, durable integration
rather than browser automation or an unofficial-account hack.

The first delivery bound Roy's own WeChat to his existing y-agent account. The
next requirement is multi-peer: one ClawBot serves several WeChat peers, each
peer is bound to one admitted y-agent user, and each conversation reaches that
user's own manager chat and execution environment.

Wu's onboarding remains user-initiated. She must create and be admitted to her
own y-agent account before binding. This feature does not contact her, create
her account, or provision her environment.

## Solution

Add a host-owned WeChat channel beside Telegram. Tencent publishes the
`@tencent-weixin/openclaw-weixin` channel plugin and a protocol document
addressed to "developers implementing or integrating a compatible backend". The
channel speaks that documented Weixin ClawBot protocol against
`https://ilinkai.weixin.qq.com`:

- QR login binds one Weixin ClawBot identity and returns `bot_token`,
  `ilink_bot_id`, `baseurl` and the scanning account's `ilink_user_id`.
- `POST /ilink/bot/getupdates` long-polls inbound direct messages with a cursor.
- `POST /ilink/bot/sendmessage` replies with the `context_token` from the
  inbound message.
- Direct chats only; groups are not part of the capability.

One ClawBot account serves several WeChat peers. Each peer is bound to exactly
one existing, admitted y-agent user, and each user has at most one peer. The
bridge remains one long-running process that polls the bot and carries every
peer's text, peer id and context token. It never holds a user's node
credential.

Binding is self-service. The maintainer binds the bot with the operator QR flow.
A second user, signed in through their own `y login`, asks the API for a binding
session, scans a QR whose provider exchange is performed by the API, and
confirms by sending a fresh six-digit code from that WeChat account. The second
user never receives the bot token. Each user's messages reach their own manager
chat, which executes on that user's own node with that user's own credentials
and work directory.

## User Stories

1. As Roy, I want to bind my own WeChat to my existing y-agent account, so that
   my WeChat conversation reaches the same assistant I already use.
2. As Roy, I want the binding to be available from the account signed in with
   `y login`, so that onboarding needs no web UI.
3. As Roy, I want the QR binding to require a fresh one-time code sent from the
   WeChat side, so that a forwarded or leaked QR cannot attach a stranger.
4. As Roy, I want the binding to target an existing, admitted user rather than
   create an account implicitly, so that admission stays the single gate for
   who may use y-agent.
5. As a second admitted user, I want to attach my own WeChat to my own account
   alongside Roy's WeChat, so that we share one bot without sharing an
   identity.
6. As a second user, I want to start the binding from my own `y login` session,
   so that Roy cannot bind my WeChat for me and I cannot bind his.
7. As a second user, I want the binding to prove control of my own WeChat
   through a one-time code, so that knowing the bot or seeing a QR is not
   enough to attach my account.
8. As a second user, I want the shared bot credential to remain on the operator
   side, so that my node cannot read or impersonate another peer's
   conversations.
9. As a second user, I want my messages to land in my own manager chat, so that
   my threads, todos, notes and files stay separate from Roy's.
10. As a second user, I want my manager turns to execute on my own node, work
    directory and credentials, so that Roy's shell tools cannot read my files
    and mine cannot read his.
11. As a second user, I do not want to be able to bind before my account has
    its own execution node, work directory, credentials and a usable bot, so
    that a half-provisioned account cannot silently run on someone else's
    machine.
12. As a second user, I want ordinary text and readable replies in the same
    WeChat conversation, so that the channel is usable without a web UI.
13. As a user, I want conversation continuity across agent turns, bridge
    restarts and process restarts.
14. As a user, I want long answers split into readable WeChat messages instead
    of raw markdown or a wall of code fences.
15. As a user, I want `/new` or `/clear` to restart my own conversation, so
    that old context does not follow me forever.
16. As a user, I want a sender that is not a bound peer to be refused, so that
    finding the bot does not grant access.
17. As a user, I want a forwarded code from another WeChat account not to
    activate my binding, so that a leaked code cannot attach a stranger.
18. As a user, I want repeated wrong codes to be rate-limited and to expire, so
    that the six-digit code cannot be brute-forced.
19. As a user, I want bot tokens, context tokens and queued message bodies
    protected by the existing tenant encryption path when my account is active,
    binding codes and provider PINs never stored in plaintext, and none of them
    printed in logs or command output.
20. As a user, I want the bridge to restart without losing the poll cursor or
    duplicating messages, so that I see no gaps or double replies.
21. As a user, I want a bounded per-peer outbound queue, so that a WeChat
    outage or an expired context token does not lose my reply or grow without
    limit.
22. As a user, I want y-agent-initiated messages such as finished work or
    reminders to reach me over WeChat on a best-effort basis when they are
    explicitly sent, queued until my next message refreshes the context.
23. As a user, I want one reply in WeChat for a WeChat DM, even when Telegram
    is bound and selected. Other manager replies follow the notify gateway
    for that user's own account.
24. As a user, I want a status command showing my binding state, last poll time
    and last delivery error, so that I can diagnose without reading another
    peer's message bodies.
25. As Roy, I want a status view that lists every bound peer by account, peer
    id and user, with no message bodies, so that I can operate the channel
    without reading other users' conversations.
26. As a user, I want to unbind or revoke my own peer, so that a lost or
    replaced phone can be cut off.
27. As Roy, I want to revoke any peer as the operator, so that I can recover
    from a lost phone or a compromised binding without waiting for that user.
28. As a user, I want re-binding my own account to replace my old peer, so that
    I do not accumulate stale bindings.
29. As Roy, I want rebinding the same ClawBot to keep other peers, and
    switching to a different ClawBot to require every peer to rebind, so that
    credentials and peer identities never cross bots.
30. As Roy, I want revoking the last peer to stop the bot's poll, while
    revoking one of several peers leaves the others working.
31. As a user, I want my admission to be re-checked on every inbound message
    and every delivery, so that an account that loses admission stops reading
    and sending immediately.
32. As the operator, I want the bridge to authenticate to the API with a
    per-account token, so that it never needs database access or tenant keys.
33. As the operator, I want one bridge process to serve all peers, so that
    adding a peer does not add a second poller or a second bot credential.
34. As a user, I want the channel to make no end-to-end-encryption claim, and
    to state plainly what the operator and the model provider can still read.

## Implementation Decisions

### Protocol ownership and version

The channel is a native Python client of the documented Weixin ClawBot protocol.
It does not install OpenClaw or run WeClaw's agent loop. We depend on the public
protocol document and the package's request shapes, not on Tencent's plugin
internals. `channel_version` in `base_info` is y-agent's own three-number version
with a suffix, for example `3.0.1/y-agent-1.0.0`, so the backend can identify the
client without pretending to be OpenClaw.

The documented access-control section admits senders beyond the QR scanner, so a
second WeChat peer can reach the same bot. The design assumes that a fresh QR
exchange by a second WeChat account returns the same `ilink_bot_id` without
rotating the bot credential, and that the scanning account's `ilink_user_id`
equals that account's later inbound sender id. Both assumptions must be
confirmed on a real second account before this delivery is accepted; v1 assumed
the second for Roy but did not confirm it. A `binded_redirect` result or a
credential rotation is a blocker, not permission to reuse credentials or to
switch to an undocumented binding path.

### Components

- **Bridge daemon** (`y wechat bridge --bot default`): runs as `ubuntu` on the
  always-on relay host `claude-relay` under the systemd unit
  `y-agent-wechat-bridge.service`. It holds one long poll for the ClawBot
  account, persists `get_updates_buf` and context tokens locally with mode 0600,
  sends outbound rows for every peer, and talks to the API only over HTTPS with
  the account's bridge token. Adding a peer does not add a process or a bot
  credential.
- **API channel routes**: a bridge-authenticated route group for inbound,
  outbound claim and ack, and heartbeat, plus user-authenticated routes for
  binding, status, unbind and explicit send. The API performs the provider QR
  exchange for binding. The API and the relay bridge are the only long-lived
  holders of the bot credential; a maintainer's binding command receives it
  transiently to write the bridge state. A bridge route never returns another
  peer's data.
- **Storage**: `wechat_account` (bot identity, encrypted bot token, bridge token
  hash, status), `wechat_peer` keyed by account and provider peer id with a
  unique bound user id, `wechat_binding` (durable QR session owned by the
  requesting user), `wechat_context` (account and peer to the latest
  `context_token`), `wechat_outbox` (pending reply, peer, owner, attempts,
  outcome), and an inbound dedupe record keyed by account and provider message
  id. Context and outbox rows carry the peer owner's user id, never the bot
  owner's.
- **Delivery hook**: the worker sends WeChat-origin manager replies through
  that peer's WeChat outbox instead of the gateway, resolving the peer from
  the reply's generation, because only the bridge holds the bot token and
  context tokens.

### Identity and ownership

- The account row owns the ClawBot credential and the bridge token. Its user id
  is the maintainer who bound the bot. The peer row owns the conversation. Its
  user id is the admitted user.
- Account-owner identity must never be used to route a conversation, authorize a
  peer, enqueue a reply or show a status. Every peer-scoped operation resolves the
  peer first and uses the peer owner.
- One peer per user and one user per peer are enforced by uniqueness. A WeChat
  account already bound to another user cannot be bound again.
- `generation` is per peer. A reply is enqueued only when the triggering user
  message carries that peer's generation, so a stale or cross-peer message
  cannot enter another peer's outbox.
- The manager chat is resolved by the peer owner's user id and the manager role.
  No chat, todo, note, file or credential is shared between peers.
- Status, unbind and send target only the caller's own peer. The maintainer's
  status lists every peer by account, peer id and user without message bodies,
  and the maintainer's explicit revoke is the only cross-peer action.

### Binding: maintainer (bot owner)

1. The maintainer runs `y wechat login` from a host with their saved `y login`.
   It binds only the y-agent account signed in there; there is no email or user
   override. Without a valid saved login, the command tells the operator to run
   `y login` before showing a QR code.
2. The command starts a short-lived binding session through the API. The API
   requests the provider QR and returns only the displayable QR content and a
   session id. The command writes a PNG of the QR under
   `~/.y-agent/wechat/<bot>.png` (mode 0600), prints its absolute path and polls
   the API. The command does not render a terminal QR.
3. The API handles the provider status exchange server-side with a bounded wait
   per request, so no API invocation is held for the full provider long poll.
   The scanning account's `ilink_user_id` is recorded against the requesting
   user, but the peer stays `pending` until that WeChat account sends the
   six-digit code as its first message within ten minutes. A QR scanned by
   someone else therefore cannot complete the binding.
4. On confirmation the peer becomes `active`, the code is consumed, and later
   messages are accepted only from that peer id. `binded_redirect` means the
   ClawBot is already bound elsewhere; the flow stops with an explicit message
   instead of reusing credentials.
5. The provider returns the bot token to the API. Only a maintainer-authenticated
   response may return the bot credential, and the maintainer's command uses it
   to create or refresh the bridge state file (mode 0600) that is installed on
   the relay host. No non-maintainer response ever contains it.
6. Binding sessions are single-use. Expiry, cancellation and a second scan
   invalidate them. `y wechat unbind` moves the caller's peer to `revoked`;
   revoking the last active or pending peer stops the bot's poll. Rebinding is a
   new binding flow.

### Binding: second user (peer only)

1. Preconditions are checked before any QR is shown: the caller is admitted, the
   caller's identity comes only from the authenticated session, a ClawBot account
   is already active, the caller has no live binding session, and the caller's
   account has its own enabled default execution node, work directory,
   credentials and at least one enabled bot. A missing precondition refuses with
   an actionable message and creates no session.
2. The caller runs `y wechat bind` in their own `y login` session. The API
   creates a binding session owned by that caller and returns the QR content and
   session id. The caller's CLI writes the PNG with mode 0600, prints the path and
   polls the API. The CLI never receives the bot token, and it writes no bridge
   state.
3. The API performs the provider QR status exchange. Statuses `wait`, `scaned`,
   `need_verifycode`, `expired`, `verify_code_blocked` and
   `scaned_but_redirect` are handled as the protocol documents. When the provider
   asks for a PIN, the user enters it in their own terminal and the CLI relays it
   for that poll only; the PIN is never stored server-side.
4. On `confirmed`, the API requires the returned `ilink_bot_id` and base URL to
   equal the active account's, and the returned bot token to match the stored
   credential. It records the scanning account's `ilink_user_id` as the caller's
   pending peer and generates a six-digit code. A differing value is an
   unexpected credential change, so the session stops without overwriting the
   account; only the maintainer can rebind a changed bot.
5. If the provider returns `binded_redirect`, a different bot id or credential,
   or any unknown state, the session stops with an explicit message, creates no
   peer and changes no existing peer.
6. The six-digit code is printed only in the requesting caller's terminal. The
   caller sends it as their first message from that WeChat account within ten
   minutes. The API activates the peer only when the sender id equals the pending
   peer id and the code matches. A message from any other WeChat account,
   including a forwarded code, cannot activate it.
7. Wrong codes are bounded. After five consecutive failed codes the pending peer
   is revoked and the caller starts again. Codes expire after ten minutes and
   per-peer code attempts are rate-limited.
8. On success, an existing peer for the same user is revoked and its contexts and
   pending outbox rows are removed in the same transaction. The caller's CLI
   reports the active binding and no bot credential.

### Provisioning gate for non-maintainers

A non-maintainer cannot bind unless all of the following already exist for that
user:

- an enabled execution node named `default` with a non-empty work directory and
  usable connection material;
- that user's own credentials on that node, not the maintainer's;
- at least one enabled bot configuration.

The channel checks these and refuses with a message naming what is missing. It
does not create nodes, work directories, credentials or bots, and it never falls
back to the maintainer's node. Node and credential provisioning belong to the
tenant provisioning path. The first concrete second user is the already admitted,
already provisioned non-maintainer account; Wu is not contacted.

### Message flow

Inbound:

1. The bridge posts each non-bot `WeixinMessage` to the API with account id,
   provider message id, sender id, text, the message's own media hint,
   `context_token`, and its structured `quote` when the message carries a
   `ref_msg`.
2. The API rejects unknown, revoked or paused accounts, deduplicates by provider
   message id before touching chat, and applies a per-peer inbound rate cap.
3. The API resolves the sender's peer row:
   - unknown sender: one fixed refusal notice, no turn;
   - pending peer: verify the code from that same sender with a bounded failure
     count, then activate or revoke, no turn;
   - active peer: re-check the peer owner's admission and continue.
4. Non-text items receive one fixed "text only for now" notice and create no
   turn. Their text, media kind and media name are still stored on the inbound
   receipt so a later quote of that message can show a media placeholder.
5. A reply or selected quote goes through the shared
   `storage.service.inbound_quote` formatter: `> [Quoted assistant]: …` for a
   bot message, `> [Quoted you]: …` for a user message, truncated at 500
   characters, separated from the typed text by a blank line. An inline
   `ref_msg` text (including a `voice_item.text` transcript), title or media
   hint is used directly; an ID-only quote
   resolves `svr_id` against `wechat_outbox.provider_message_id` (bot messages)
   or `wechat_inbound.message_id` (user messages), filtered strictly by
   `(account, peer, user_id)`. A selected substring (`partial_text`) is
   resolved against the stored body with the client's `quotemd5`; a miss falls
   back to the full body. A quote whose content is gone, foreign, or from
   another peer becomes `[Quoted earlier message: content unavailable]`, never a
   silent drop and never another peer's text.
6. Text that starts with `/<chat_id> ` or `/<todo_id> ` goes to that peer
   owner's chat through `accept_user_message` with `source="wechat"` and
   `human_reply=True`. A todo prefix resolves through the shared
   `storage.service.inbound_route` resolver to the todo's handle chat,
   otherwise its latest trace chat, and never creates a chat. Neither prefix
   resets the manager session. A missing or foreign chat gets one outbox
   notice, `chat /<id> not found`; a missing, foreign, closed, or
   shared-read-only todo gets one outbox notice (`todo /<id> not found`,
   `todo /<id> is closed`, `todo /<id> is shared read-only`). Neither opens a
   turn. The receipt resumes the target chat with its own role, skill, trace
   and work dir. Legacy bridges that still pre-flatten a quote as leading
   `> ` lines keep working, and the identical quote is not duplicated.
7. Other text reaches the peer owner's manager chat through the existing
   append-or-steer path with `source="wechat"` and `human_reply=True`; a new
   manager chat is created when none exists. `/new` and `/clear` restart that
   manager session, mirroring Telegram, and a quote attached to `/clear` does
   not survive the reset.
8. The inbound receipt records the resolved owner and the queued run, so a
   replay delivers to the same user or fails closed if the peer is no longer
   active. It also stores the message text, media kind and media name for
   future quote resolution under the tenant-encryption fields of
   `wechat_inbound` (`quote_text`, `media_name`).

Outbound:

1. A manager reply is enqueued only when the turn was triggered by a WeChat
   message carrying the peer's generation and the reply belongs to that peer's
   owner. Explicit send (`y wechat send`) and a proactive notice selected by the
   [notify gateway](notify-gateway.md) use that same per-peer queue. The gateway
   addresses one user's own peer; it does not fan a routine or reminder out to
   every peer.
2. The bridge claims rows across all peers with the account token, sends
   `sendmessage` with that peer's latest `context_token`, and acks the result.
   A missing or expired token leaves the row `blocked_on_context`; it is
   delivered after that peer's next inbound message refreshes the token.
   Failures retry with bounded backoff and then become a visible per-peer
   operator error, never an unbounded loop.
3. Markdown becomes WeChat-readable plain text: code fences and markup removed,
   links reduced to display text, artifact fences reduced to the same
   placeholders Telegram uses. Long messages are split with an explicit
   continuation marker.
4. One peer's queue, retries or failures never block or consume another peer's
   delivery.

WeChat-origin manager turns get no mirror and reply only through that peer's
WeChat outbox, even when Telegram is bound and selected. Other manager replies
and non-channel pre-run mirrors use the [notify gateway](notify-gateway.md),
with its configured preference and fallback, addressed to the chat's own user.
A Telegram-triggered turn never enqueues a WeChat reply unless that gateway
selects WeChat for the same user. One user's delivery never reaches another
user's Telegram or WeChat.

### Revocation and replacement

- A user can unbind only their own peer. The maintainer can revoke any peer
  through an explicit maintainer-only path. Revocation deletes that peer's
  contexts and pending outbox rows and never touches another peer.
- Revoking the last active or pending peer revokes the bot account, clears the
  bridge credential and stops the poll. Revoking one of several peers leaves the
  account active and the other peers working.
- Re-binding the same user replaces the old peer atomically at activation. A
  user cannot hold two peers at once.
- A maintainer rebind that returns the same bot id keeps every peer and rotates
  the bot credential; the operator refreshes the bridge state and restarts the
  bridge. A different bot id revokes every peer, invalidates every live binding
  session, and requires each user to bind again.
- Expired or cancelled sessions are single-use, leave no active peer and do not
  disturb an existing active peer.

### Isolation and deployment

- Each peer belongs to exactly one user; account and peer resolution are
  owner-scoped and fail closed.
- The relay hosts the bridge, not a user execution environment. Each peer's
  manager chat runs on that peer owner's own default node, work directory and
  credentials. The channel never passes a node, work directory or credential
  across peers.
- The bridge stores only the bot credential, the poll cursor and its bridge
  token. It has no database URL, no tenant master key and no per-user
  credential.
- A per-peer inbound rate cap and a bounded per-peer outbox prevent runaway
  loops between the assistant and WeChat.
- Logs carry account, peer, message ids and outcomes, never message bodies,
  tokens, QR payloads or binding codes.

### Encryption

The channel adds no new cryptography. Its classified fields register in the
existing classification registry: the account bot token under the bot owner,
and peer context tokens and queued text under each peer owner. Binding codes are
stored hashed, the QR session stores no bot credential, and a provider PIN is
relayed per request and never stored. Each peer's classified rows are sealed and
opened by the existing flush and load hooks under that peer owner's tenant key
when the owner is tenant-encryption-active. The two users' rows are
independently encrypted.

Encryption eligibility and activation remain the existing hosted-tenant rollout
(`docs/prd/hosted-tenant-confidentiality.md`); this feature neither changes
eligibility nor claims coverage for an inactive owner. Roy's personal account is
not currently encryption-active, so his channel data is plaintext at rest and
readable from database copies. A tenant-encryption-active peer's data is sealed.
This is not E2EE: the execution node, relay, provider and a process holding the
master key can read plaintext.

### Operational notes

- Apply the multi-peer migration before enabling the new routes. The bridge's
  wire behavior is unchanged; the API and CLI deploy in lockstep.
- The API must reach the provider over HTTPS from the deployed runtime. If that
  egress is unavailable, binding cannot run; the delivery must not fall back to
  handing the bot token to a client.
- The account row remains the serialization point for binding, activation and
  revocation. Per-peer operations lock consistently so two users cannot activate
  or replace the same peer concurrently.
- The bridge state file is operator-owned with mode 0600. A bot-credential
  rotation requires refreshing it from the authenticated maintainer surface and
  restarting the bridge. Never run two pollers at once.

## Testing Decisions

Verification targets external behavior at the channel boundary.

- A deterministic local stub of the iLink HTTP API exercises QR states (`wait`,
  `scaned`, `confirmed`, `expired`, `need_verifycode`, `verify_code_blocked`,
  `scaned_but_redirect`, `binded_redirect`), cursor persistence across a
  simulated restart, duplicate provider message ids, unbound-sender refusal,
  wrong-code limits and expiry, outbox retry and `blocked_on_context` recovery.
- Multi-peer checks use two admitted users and two peers: binding a second peer
  from the second user's own session, the first user's peer and outbox
  unaffected, each inbound routed to the correct manager chat, each reply
  enqueued only for the triggering peer and owner, cross-peer status and outbox
  isolation, and one bridge process claiming both peers' rows.
- Security checks assert that a non-maintainer response never contains the bot
  token or another peer's identity, that one user cannot bind, unbind, send as or
  read status for another user, that a forwarded code from a different WeChat
  account cannot activate a pending peer, that a peer already bound to another
  user cannot be rebound, and that an unadmitted or de-admitted user cannot bind,
  open a turn or receive a delivery.
- Provisioning checks assert that a non-maintainer without an enabled default
  node, work directory, credentials or a usable bot is refused before a QR is
  shown.
- Revocation checks assert that owner unbind and maintainer revoke affect only
  the target peer, that the last-peer case stops the bot, and that rebinding the
  same bot id keeps other peers while a different bot id revokes them.
- Telegram negative controls assert that a Telegram-triggered turn creates no
  WeChat outbox row and that a second user without a Telegram binding receives
  no Telegram delivery.
- The live gate needs two real WeChat accounts: bind Roy's, bind the second
  user's from that user's own CLI, exchange two turns on each, restart the
  bridge, exchange a third turn on each, and confirm continuity without
  duplicate replies. It also unbinds one peer while the other keeps working and
  records the provider's exact response to the second QR exchange. The delivery
  record states which steps need a phone and what stays unverified if a second
  phone or account is unavailable. Wu is not contacted; the concrete second
  account is the already admitted, already provisioned non-maintainer user.

## Out of Scope

- Wu's account creation, admission, node provisioning, bot configuration and
  credentials. These are user-initiated and owned by the tenant provisioning
  path; the channel fails closed until they exist.
- A code-only peer-binding path for a provider that refuses a second QR. If the
  live gate returns `binded_redirect` for a second WeChat account, the delivery
  returns to the user with evidence; it does not silently change the binding
  model.
- More than one ClawBot account per deployment, or more than one peer per user.
- Binding from the web UI; the second user binds from their own CLI.
- Cross-peer administration beyond the maintainer's revoke. There is no
  maintainer send-as another peer and no reading of another peer's message
  bodies.
- WeChat group chats; images, voice, files and video in either direction beyond
  a fixed text notice for inbound media.
- The WeChat Official Account and WeCom (企业微信) surfaces.
- End-to-end encryption, and any claim that the operator cannot read content.
- Changing tenant-encryption eligibility, key custody or activation.
- Billing, quotas and cost controls for model usage.
- Streaming, message editing and typing indicators in WeChat.
- Generalizing Telegram and WeChat into a shared multi-channel framework; the
  channel keeps its channel-specific slice.
