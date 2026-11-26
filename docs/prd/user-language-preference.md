---
title: User Language Preference
type: prd
project: y-agent
feature: user-language-preference
status: active
---

# User Language Preference

## Problem Statement

The kernel hardcoded two opposite language rules for text the agent writes on
a person's behalf. Agent-authored awaiting notices and fault sentences were
written in Chinese, while stored todo `name` / `desc` / `--progress` and
cross-session dispatch callbacks were required to stay English. Both were
always-on rules in the always-loaded instructions, so every session paid for
them and every user got the same output regardless of who owned the work.

Those defaults fit one user. A preference makes the language an explicit,
per-user setting that other sessions and worker processes can read, while
leaving existing rows and existing behavior unchanged until someone opts in.

## Solution

Store one preference, `user_preference.language`, as a plain string
(`en` or `zh`; missing or invalid reads `en`). The generic authenticated
`/api/user-preference` route already reads and writes any key, so there is no
new table and no schema change. `y preference get|set language` is the set
surface: `get` prints the effective value, `set language en|zh` stores it, and
`set language default` clears the row back to `en`.

The preference is a closed set on purpose. Every localized sentence is a
maintained catalog entry, so a free-form value could not be rendered. The
renderers fall back to `en` on read instead of failing, so a row written by a
newer release never breaks a notice.

Stored todo `name` / `desc` / `progress` follow the owner's language at write
time. A preference change never rewrites existing rows, so historical todos stay
as they are. Agent-authored notices follow the language of the person receiving
them: the todo owner for worker faults, and the authenticated user the writing
session runs as elsewhere. A share reader still sees the owner's stored text
unchanged; any new summary they write follows the reader.

Commit messages and committed repository documentation stay English, because
they follow the repository convention rather than a personal preference. The
parent-chat death dispatch also stays English: it is agent-to-agent evidence,
not user-facing text.

## User Stories

1. As a user, I want my stored todo fields written in the language I read, so
   that `y todo get` and cross-session handoff are not needlessly English.
2. As a user, I want to opt into Chinese or stay on the English default with
   one CLI command, so that the choice does not require editing configuration.
3. As a user, I want my awaiting DMs, watchdog and death fault sentences in my
   language, so that the one message that asks me to act is readable at a
   glance.
4. As a user, I want raw error excerpts and outcome tokens left verbatim, so
   that the evidence stays searchable and is never mistranslated.
5. As a user, I want a preference change not to rewrite or translate existing
   todos, so that history and shared views stay stable.
6. As a user, I want an unset or invalid preference to behave exactly like the
   English default, so that a missing setting can never fail a write or a
   notice.
7. As a share recipient, I want the owner's stored todo text shown unchanged,
   so that I read what the owner actually wrote.
8. As a session, I want to read the preference through `y preference get`, so
   that dispatch text and callbacks match the acting user.
9. As a maintainer, I want commit messages and repository docs to stay English,
   so that the repository convention does not depend on who ran the session.
10. As a parent session, I want a child death dispatched to me in English, so
    that agent-to-agent evidence stays in one language.

## Implementation Decisions

- **Storage**: `user_preference` key `language`, values `en|zh`, same shape as
  `notify_channel`. No schema change. `get_language` treats a missing row, a
  non-string value, or an unknown value as `en`; `set_language(None|'default')`
  deletes the row.
- **Read/write surfaces**: `storage.service.user_preference` owns
  `LANGUAGE_KEY`, `LANGUAGES`, `DEFAULT_LANGUAGE`, `get_language`,
  `set_language`. The CLI imports those constants and uses the existing
  authenticated `/api/user-preference` route. No dedicated API route and no
  server-side rejection are added: the CLI enforces `en|zh|default`, and the
  read path already falls back, so a direct free-form write is inert.
- **Resolution actor**: the authenticated user the session runs as. Owner work
  resolves the todo owner; a share recipient writing a summary resolves the
  recipient. Worker fault notices resolve the owner's internal user id because
  that is who receives the DM.
- **Notices**: `storage.service.todo_notice` holds the heading and fault
  catalogs plus the moved `validate_notice` / `notice_excerpt` helpers. Heading
  is `[Progress] <id>` for `en` and `【进度】<id>` for `zh`, with no name and no
  reply instruction. Fault sentences are `idle`, `backstop`, `session_end`,
  `attention`, lapsed `machine_wait`, and the death prefix. The newest-chat
  suffix exists only when a chat id is known.
- **Untranslated evidence**: raw error excerpts, exit outcome tokens
  (`completed|error|timeout|unknown`), chat and todo ids are printed as-is.
- **Worker paths**: the trace-liveness watchdog and session-end reconcile
  resolve the owner's language once per claim and pass it into the fault
  builder; the death delivery resolves it once and uses the localized prefix
  for the owner DM and inbox notice, while the parent-chat dispatch is built
  from the English catalog entry.
- **Writer-supplied text**: `--note` / `notice` is accepted in any language; it
  follows the same length and credential-shape validation as before and is
  folded into the same history entry.
- **Config text is not part of the host repository**: the always-loaded
  instruction wording that tells sessions to read the preference belongs to the
  deployment configuration repository and is updated there, uncommitted,
  after the host deploy is verified. The host code only names `y preference`
  and keeps an English fallback for an older installed CLI.

## Testing Decisions

- Pure renderer checks: heading and fault catalogs return the expected literal
  per language and never raise for a known key.
- Preference resolution checks monkeypatch the repository read: missing row,
  `zh`, and an invalid value resolve to `en`, `zh`, and `en` respectively.
- Worker fault-detail checks cover `idle`, `backstop`, and `session_end` in both
  languages, assert a non-empty sentence, and assert the chat suffix appears
  only when a chat id is supplied.
- CLI help exposes `language` with the choices `en|zh|default`.
- Deployed checks: `y preference get language` returns `en`; setting `zh` makes
  a new awaiting DM use `【进度】` and new stored fields follow the chosen
  language; clearing back to `default` restores `[Progress]`.
- A shared read by a differently-preferring reader leaves the stored `name` /
  `desc` / `progress` bytes unchanged.

## Out of Scope

- Localizing skills that hardcode a non-English default elsewhere
  (`learning`, `check-in`, weekly journal).
- Note heading and file-name language.
- WeChat / Telegram media placeholders and the parent-chat death dispatch.
- Rewriting or translating historical todos.
- A web settings control, separate record/notice language keys, or free-form
  languages. The CLI is the set surface until a second language gains enough
  audience to justify a control.
