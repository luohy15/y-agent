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
next requirement is per-user bots: each admitted user binds their own iLink bot
account from their own `y login`, and each conversation reaches that user's own
manager chat and execution environment. The iLink QR flow proved that every scan
mints a new bot (evidence: `pages/onboarding-4490-wechat-bind.md`), so a shared
bot cannot be the multi-user model.

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

Each admitted user owns at most one bot account, and each bot account has at
most one bound WeChat peer owned by that same user. The relay runs one
long-running bridge process that polls every active bot account in parallel and
carries each account's peer text, peer id and context token. It never holds a
user's node credential.

Binding is self-service for every admitted user, including the maintainer. The
user, signed in through their own `y login`, asks the API for a binding session,
scans a QR whose provider exchange is performed by the API, and confirms by
sending a fresh six-digit code from that WeChat account. The bound bot belongs
to the user who scanned. The user never receives the bot token. Each user's
messages reach their own manager chat, which executes on that user's own node
with that user's own credentials and work directory.

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
5. As a second admitted user, I want to attach my own WeChat with my own bot
   alongside Roy's, so that each of us has an independent bot identity.
6. As a second user, I want to start the binding from my own `y login` session,
   so that Roy cannot bind my WeChat for me and I cannot bind his.
7. As a second user, I want the binding to prove control of my own WeChat
   through a one-time code, so that knowing the bot or seeing a QR is not
   enough to attach my account.
8. As a user, I want my bot credential to remain on the API and relay side, so
   that my node cannot read or impersonate another user's conversations.
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
25. As a user, I want a status view that lists my own bot account and peer by
    id, with no message bodies, so that I can operate my binding.
26. As a user, I want to unbind or revoke my own peer, so that a lost or
    replaced phone can be cut off.
27. As the deployment operator, I want each bot account's poller to be
    isolated, so that one user's failure or revocation never stops another
    user's bot.
28. As a user, I want re-binding my WeChat to replace my previous bot account
    and peer, so that I do not accumulate stale bindings.
29. As a user, I want rebinding the same bot to keep my existing peer and
    switching to a new bot to replace only my own account, so that credentials
    and peer identities never cross users.
30. As a user, I want revoking my last peer to stop my own bot account's poll,
    while other users' bots keep working.
31. As a user, I want my admission to be re-checked on every inbound message
    and every delivery, so that an account that loses admission stops reading
    and sending immediately.
32. As the operator, I want the bridge to authenticate to the API with one
    deployment key, so that it never needs database access, tenant keys or a
    per-account token.
33. As the operator, I want one bridge process to serve every active bot
    account, so that adding a user does not add a second poller or a second
    relay deployment.
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

Every QR exchange mints a new bot account. The live onboarding check
(`pages/onboarding-4490-wechat-bind.md`) showed a second scan returning a
different `ilink_bot_id`, so the channel keys one bot account and one bound peer
per user instead of assuming a shared bot. The scanning account's
`ilink_user_id` is recorded as that bot's pending peer and must equal the
sender id of the six-digit confirmation message. A `binded_redirect` result is a
terminal failure, not permission to reuse credentials or to switch to an
undocumented binding path. Orphaned bots left by earlier scans are provider-side
and are not cleaned up by this feature.

### Inbound media

The bridge never downloads media. It forwards, for up to nine image, file or
voice items, a descriptor with the kind, the provider CDN url or encrypted query
param, the AES key in both spellings the client uses, and (for a file) its name
and declared size or (for a voice note) its `playtime`, `encode_type` and
`sample_rate`. The API fetches because the bridge-to-API body is capped at
600 KB and the Lambda request at 6 MB, while one file may be 20 MB; keeping the
bytes out of the bridge also keeps it credential-only with no crypto or storage.

The API validates before fetching: HTTPS only, no userinfo, port 443, a host
under `*.cdn.weixin.qq.com`, every resolved address public, and no redirects.
It streams with a 10 MB image cap, a 20 MB file cap and a 4 MB voice cap. The
provider's blob is AES-128-ECB with PKCS7 padding; the key is a raw
32-character hex `aeskey` (an image's preferred field) or a base64 `aes_key`
that decodes either to the 16 raw bytes or to 32 hex characters. A JPEG, PNG,
GIF or WEBP image is stored unchanged; HEIF/HEIC (an iOS original) is
re-encoded to an RGB JPEG. Files reuse the same classifier and storage path as
Telegram: no file type is rejected, the name is sanitized, and the cap is
20 MB. Because those helpers are shared, the Telegram document path accepts
executable and installer suffixes too now, and its former "file type is not
supported" reply is gone. The descriptor is never persisted; only the stored
paths are, on `Message.images` and `Message.files`. This adds no DDL and no
tenant-encryption field.

A voice note takes no EC2 asset path: the API decodes the decrypted SILK to
16 kHz mono PCM16 (`api.util.voice_transcode`, capped at 120 seconds and
3,999,956 PCM bytes) and uploads it to the published `voice` module in-process
through `api.util.gateway_voice`, bound to the sending peer's own user. The
module transcribes and polishes it, and its take lands in that user's Voice
archive. A jump node or an `agy` chat accepts voice even though it refuses
images, because only plain text reaches the chat. Every rejection (fetch,
decrypt, unsupported codec, over the size or duration cap, node or module
unavailable, empty transcript) produces one explicit outbox notice. Telegram
rides the same service, so both channels share one archive and one transcript
quality. The provider's own `voice_item.text` is used only when the item carries
no CDN descriptor; otherwise the module transcript is the body and the stored
`quote_text`.

One message may carry several voice items (a real message carried two). Each
item is transcribed into its own take, and the single user message records
every take in `voice.takes`, in item order; the web composer sends the same
multi-take shape, and a legacy single `{take_id, duration_ms}` reference is
still read.

A bridge that sends `media_items` requires this API version. An old API rejects
the payload with 422 and loses that message, so deploy and verify the API before
restarting the bridge. The voice path also needs the Voice module published with
`dispatch_scope: authenticated`; until then the pre-check rejects with the "not
enabled for this account" notice instead of fetching.

### Components

- **Bridge daemon** (`y wechat bridge --bot default`): runs as `ubuntu` on the
  always-on relay host `claude-relay` under the systemd unit
  `y-agent-wechat-bridge.service`. It holds one poll thread per active bot
  account, listing accounts from the API every 30 seconds, and persists each
  account's `get_updates_buf` and unacked sends locally with mode 0600. It talks
  to the API only over HTTPS with one deployment bridge key and never receives a
  node credential. Adding a user adds a thread and an account, not a process or
  a relay deployment.
- **API channel routes**: a bridge-key-authenticated route group for the account
  inventory, inbound, outbound claim and ack, and heartbeat, plus
  user-authenticated routes for binding, status, peers, unbind, revoke and
  explicit send. The API performs the provider QR exchange for binding and is
  the only long-lived holder of bot tokens. The `accounts` route returns active
  account ids, base URLs and decrypted tokens to the bridge key holder only, and
  never to a browser. A bridge route never returns another account's data.
- **Storage**: `wechat_account` keyed by bot account with the scanning user's
  owner id, encrypted bot token and status; `wechat_peer` keyed by account and
  provider peer id with a unique bound user id; `wechat_binding` (durable QR
  session owned by the requesting user); `wechat_context` (account and peer to
  the latest `context_token`); `wechat_outbox` (pending reply, peer, owner,
  attempts, outcome); and an inbound dedupe record keyed by account and provider
  message id. A user has at most one account row and one peer. The legacy
  `slot` and `bridge_hash` columns are retained but unused.
- **Delivery hook**: the worker sends WeChat-origin manager replies through
  that peer's WeChat outbox instead of the gateway, resolving the peer from
  the reply's generation, because only the bridge holds the bot token and
  context tokens.

### Identity and ownership

- The account row owns the bot credential. Its user id is the user who scanned
  that bot, and the peer row's user id is the same user.
- Account-owner identity must never be used to route another user's
  conversation. Every account-scoped operation resolves the caller's own
  account, and every inbound operation resolves the sender's peer under that
  account.
- One account per user and one peer per user are enforced by the service and by
  `wechat_peer.user_id` uniqueness. A bot already owned by another user cannot
  be bound, and a sender already active under another user cannot be bound.
- `generation` is per peer. A reply is enqueued only when the triggering user
  message carries that peer's generation, so a stale or cross-peer message
  cannot enter another peer's outbox.
- The manager chat is resolved by the peer owner's user id and the manager role.
  No chat, todo, note, file or credential is shared between users.
- Status, peers, unbind, revoke and send target only the caller's own account
  and peer. There is no cross-user inventory, send-as or revoke surface. A
  bridge request for an inactive account returns 404, which stops only that
  account's poller.

### Binding: self-service for every user

1. Preconditions are checked before any QR is shown: the caller is admitted, the
   caller's identity comes only from the authenticated session, the caller has
   no live binding session, and the caller's account has its own enabled default
   execution node, work directory, credentials and at least one enabled bot. An
   existing bot account is not a precondition because this bind creates one. A
   missing precondition refuses with an actionable message and creates no
   session.
2. The caller runs `y wechat bind` (or `y wechat login`, an alias) in their own
   `y login` session. The API creates a binding session owned by that caller and
   returns the QR content and session id. The caller's CLI writes the PNG under
   `~/.y-agent/wechat/bind.png` (mode 0600), prints the path and polls the API.
   It renders no terminal QR, never receives the bot token, and writes no bridge
   state.
3. The API performs the provider QR status exchange with a bounded wait per
   request. Statuses `wait`, `scaned`, `need_verifycode`, `expired`,
   `verify_code_blocked` and `scaned_but_redirect` are handled as the protocol
   documents. When the provider asks for a PIN, the user enters it in their own
   terminal and the CLI relays it for that poll only; the PIN is never stored
   server-side.
4. On `confirmed`, the API requires the returned `ilink_bot_id`, bot token, base
   URL and scanning `ilink_user_id`. It resolves the caller's own account and the
   bot's current owner, then binds: a bot owned by another user is rejected; the
   caller's own bot rotates its token and base URL and keeps its peer; a new bot
   replaces the caller's own account, peer, contexts, outbox and inbound rows;
   otherwise it creates the caller's account. A sender already active under
   another user, or awaiting confirmation for another user, is rejected. The
   scanning account's `ilink_user_id` becomes the caller's pending peer and a
   six-digit code is generated.
5. If the provider returns `binded_redirect`, incomplete credentials, or an
   unknown state, the session stops with an explicit message, creates no peer
   and changes no account. `binded_redirect` is terminal, not permission to reuse
   credentials.
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
9. Binding sessions are single-use. Expiry, cancellation and a second scan
   invalidate them. `y wechat unbind` moves the caller's peer to `revoked`;
   revoking the last active or pending peer revokes the caller's own bot account
   and clears its token, leaving every other user's account untouched. Rebinding
   is a new binding flow.

### Provisioning gate

A user cannot bind unless all of the following already exist for that user:

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
   `context_token`, its structured `quote` when the message carries a
   `ref_msg`, and up to nine `media_items` descriptors for image, file and
   voice items.
2. The API rejects unknown, revoked or paused accounts, deduplicates by provider
   message id before touching chat, and applies a per-peer inbound rate cap.
3. The API resolves the sender's peer row:
   - unknown sender: one fixed refusal notice, no turn;
   - pending peer: verify the code from that same sender with a bounded failure
     count, then activate or revoke, no turn;
   - active peer: re-check the peer owner's admission. A de-admitted owner
     gets one fixed "This account is not approved." notice and no turn.
4. Image, file and voice items follow the message's text route. The target is
   resolved before any fetch, so an absent or foreign target keeps its notice
   and downloads nothing. Images are fetched from the provider CDN, decrypted
   and stored under the image assets directory; a file is stored under the
   attachments directory; a voice note is decoded and transcribed through the
   shared gateway voice service, every voice item into its own take. A
   captionless image or file message gets
   `请看这张图片` or `请看这个文件` as its text; a voice message's text joins its
   item transcripts and the message carries all of its takes. Every rejection
   (fetch, decrypt, store, too large, unsupported
   image type, unsupported voice codec, over the voice duration cap, a jump node
   without image support, an `agy` chat that refuses images, a disabled voice
   module) produces one explicit outbox notice and never a silent drop. Video
   and other non-image/file/voice items receive one fixed "text only for now"
   notice and create no turn; their text, media kind and media name are still
   stored on the inbound receipt so a later quote of that message can show a
   media placeholder.
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
   silent drop and never another peer's text. Media classification is
   type-first: an explicit `type` wins (`1` is text even beside an empty media
   stub, `2` through `5` are image / voice / file / video, any other non-text
   type is an attachment), and only a zero or absent `type` falls back to the
   payload key (`image_item` / `voice_item` / `file_item` / `video_item`),
   where an empty stub counts as absent. So a quoted attachment still renders
   `[image]` or `[file: <name>]`, and any other non-text payload stays
   `[attachment]`. The bridge prints one content-free `bridge shape` line per
   quoted or media message: item type and present key names, plus a nested
   `ref_msg` block with its keys and its `message_item` type and payload keys,
   and, for a direct image, file or voice item, the `media` object's key names.
   It never prints a value.
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
   `wechat_inbound` (`quote_text`, `media_name`). A transcribed voice note
   replaces `quote_text` with the module's final (polished) transcript, so a
   later quote shows clean text.

Outbound:

1. A manager reply is enqueued only when the turn was triggered by a WeChat
   message carrying the peer's generation and the reply belongs to that peer's
   owner. Explicit send (`y wechat send`) and a proactive notice selected by the
   [notify gateway](notify-gateway.md) use that same per-peer queue. The gateway
   addresses one user's own peer; it does not fan a routine or reminder out to
   every peer.
2. The bridge claims each active account's rows with the deployment key, sends
   `sendmessage` with that account's bot credential and the peer's latest
   `context_token`, and acks the result. A missing or expired token leaves the
   row `blocked_on_context`; it is delivered after that peer's next inbound
   message refreshes the token. Failures retry with bounded backoff and then
   become a visible per-peer operator error, never an unbounded loop.
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

- A user can unbind or revoke only their own peer. Revocation deletes that
  peer's contexts and pending outbox rows and never touches another account.
- Revoking the last active or pending peer revokes the caller's own bot account,
  clears its bot token and stops that account's poll. Every other user's account
  and poller keep working.
- Re-binding the same bot rotates its token and base URL at activation and keeps
  the existing peer. A new bot replaces the caller's own account, peer, contexts
  and outbox rows atomically; another user's account is never modified.
- A user cannot hold two bot accounts or two peers at once.
- Expired or cancelled sessions are single-use, leave no active peer and do not
  disturb an existing active peer.

### Isolation and deployment

- Each account and peer belongs to exactly one user; account and peer resolution
  are caller-scoped and fail closed.
- The relay hosts the bridge, not a user execution environment. Each peer's
  manager chat runs on that peer owner's own default node, work directory and
  credentials. The channel never passes a node, work directory or credential
  across users.
- The bridge stores only per-account cursors and unacked-send receipts, and
  reads its API base URL and deployment key from its systemd environment. It has
  no database URL, no tenant master key and no per-user node credential. Bot
  tokens are fetched fresh from the API for active accounts.
- One account's poller, failure or revocation is isolated from every other
  account's poller.
- A per-peer inbound rate cap and a bounded per-peer outbox prevent runaway
  loops between the assistant and WeChat.
- Logs carry account, peer, message ids and outcomes, never message bodies,
  tokens, QR payloads or binding codes.

### Encryption

The channel adds no new cryptography. Its classified fields register in the
existing classification registry: the account bot token under the scanning
user, and peer context tokens and queued text under each peer owner. Binding
codes are stored hashed, the QR session stores no bot credential, and a provider
PIN is relayed per request and never stored. Each user's classified rows are
sealed and opened by the existing flush and load hooks under that user's tenant
key when the owner is tenant-encryption-active. Users' rows are independently
encrypted, and the bridge key itself is a deployment secret, not a database
field.

Gateway voice input does not extend that registry. A transcribed take lives in
the `voice` module's own `voice_take` table, and the hooks are ORM listeners
installed only on the host entities listed in `storage/crypto/fields.py`; they
do not reach module-owned entities. `voice_take` (`raw_text`, `polished_text`,
`label`) therefore stays plaintext for every owner, while the archived audio
bytes still seal through `voice_store` when the owner is encryption-active.
Covering the module table needs a module-side change, not a host SPECS entry.

Inbound media adds no channel key custody. It fetches the provider's own
at-rest blob over HTTPS and decrypts it with the descriptor's AES-128-ECB key;
that is transport of the provider's encoding, not channel encryption, and it
does not change the at-rest story below. The stored image or file is an ordinary
asset read from the peer owner's node.

Encryption eligibility and activation remain the existing hosted-tenant rollout
(`docs/prd/hosted-tenant-confidentiality.md`); this feature neither changes
eligibility nor claims coverage for an inactive owner. Roy's personal account is
not currently encryption-active, so his channel data is plaintext at rest and
readable from database copies. A tenant-encryption-active peer's data is sealed.
This is not E2EE: the execution node, relay, provider and a process holding the
master key can read plaintext.

### Operational notes

- Apply `migration/4496_wechat_per_user_account.sql` before enabling the new
  routes, then deploy the API, then the relay. The bridge's wire behavior keeps
  its protocol shapes but every request now carries an account id and uses the
  deployment key. A short bridge outage during the cutover is accepted: outbox
  rows queue and inbound messages replay from each account's unadvanced cursor.
- `Y_AGENT_WECHAT_BRIDGE_KEY` must be set on the API (SAM parameter
  `WechatBridgeKey`) and in the relay's systemd `EnvironmentFile` together with
  `Y_AGENT_WECHAT_BRIDGE_API`. An empty key fails every bridge route closed; an
  unreachable API is an error, never an open bridge.
- The API must reach the provider over HTTPS from the deployed runtime. If that
  egress is unavailable, binding cannot run; the delivery must not fall back to
  handing the bot token to a client. Inbound image and file fetch needs the same
  egress to the provider CDN; if it is unavailable every media message gets its
  explicit notice instead of a silent drop.
- `pg_advisory_xact_lock(4400, 1)` serializes channel writes. Per-account row
  locks protect binding, activation and revocation so two users cannot activate
  or replace the same account concurrently.
- The bridge state file is operator-owned with mode 0600 and holds only
  per-account cursors and receipts. A missing file starts with no accounts; on
  first start after the cutover it migrates Roy's legacy single-account cursor
  instead of resetting it. Bot-credential rotation needs no state-file edit; the
  bridge refreshes accounts from the API and restarts that account's poller when
  its token or base URL changes. Never run two pollers at once.

## Testing Decisions

Verification targets external behavior at the channel boundary.

- A deterministic local stub of the iLink HTTP API exercises QR states (`wait`,
  `scaned`, `confirmed`, `expired`, `need_verifycode`, `verify_code_blocked`,
  `scaned_but_redirect`, `binded_redirect`), cursor persistence across a
  simulated restart, duplicate provider message ids, unbound-sender refusal,
  wrong-code limits and expiry, outbox retry and `blocked_on_context` recovery.
- Multi-account checks use two admitted users and two bot accounts: binding the
  second user's own bot from that user's session, the first user's account, peer
  and outbox unaffected, each inbound routed to the correct manager chat, each
  reply enqueued only for the triggering account and owner, cross-account status
  and outbox isolation, and one bridge process polling both accounts with
  independent threads and cursors.
- Security checks assert that no binding response contains a bot token or
  another user's identity, that one user cannot bind a bot owned by another
  user, unbind, revoke, send as or read status for another user, that a
  forwarded code from a different WeChat account cannot activate a pending
  peer, that a sender already active under another user cannot be bound, and
  that an unadmitted or de-admitted user cannot bind, open a turn or receive
  assistant content; a de-admitted peer receives only the fixed not-approved
  notice.
- Provisioning checks assert that a user without an enabled default node, work
  directory, credentials or a usable bot is refused before a QR is shown.
- Revocation checks assert that owner unbind and revoke affect only the
  caller's account and peer, that the last-peer case revokes only that account,
  and that rebinding the same bot keeps the peer while a new bot replaces only
  the caller's account.
- Telegram negative controls assert that a Telegram-triggered turn creates no
  WeChat outbox row and that a second user without a Telegram binding receives
  no Telegram delivery.
- The live gate needs two real WeChat accounts: keep Roy's existing account and
  peer, bind the second user's own new bot from that user's CLI, exchange two
  turns on each, restart the bridge, exchange a third turn on each, and confirm
  continuity without duplicate replies. It also unbinds one peer while the other
  account keeps working and records the provider's exact response to the second
  QR exchange. The delivery record states which steps need a phone and what
  stays unverified if a second phone or account is unavailable. Wu is not
  contacted; the concrete second account is the already admitted, already
  provisioned non-maintainer user.

## Out of Scope

- Wu's account creation, admission, node provisioning, bot configuration and
  credentials. These are user-initiated and owned by the tenant provisioning
  path; the channel fails closed until they exist.
- A fallback for a provider that returns `binded_redirect`. The session stops
  with evidence; the delivery does not silently change the binding model.
- More than one bot account per user, or more than one peer per user.
- Cleaning up orphan iLink bots left by earlier scans; the provider exposes no
  cleanup API for them.
- Binding from the web UI; every user binds from their own CLI, and the gateway
  module panel copy is a separate follow-up.
- Cross-user administration. There is no operator inventory, send-as or revoke
  across users' accounts, and no reading of another user's message bodies.
- WeChat group chats; video and other non-image/file/voice inbound media, and
  outbound media in either direction beyond the fixed inbound text notices.
  More than nine media items in one message are not supported. Legacy AMR/MP3
  voice notes are rejected with an explicit unsupported-format notice.
- The WeChat Official Account and WeCom (企业微信) surfaces.
- End-to-end encryption, and any claim that the operator cannot read content.
- Changing tenant-encryption eligibility, key custody or activation.
- Billing, quotas and cost controls for model usage.
- Streaming, message editing and typing indicators in WeChat.
- Generalizing Telegram and WeChat into a shared multi-channel framework; the
  channel keeps its channel-specific slice.
