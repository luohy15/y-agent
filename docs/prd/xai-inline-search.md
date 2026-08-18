---
title: xAI Inline Search Backends
type: prd
project: y-agent
feature: xai-inline-search
status: active
---

# xAI Inline Search Backends

## Problem Statement

y-agent needs grounded, current answers from two sources that ordinary model
knowledge cannot reliably cover: the public web and public posts on X. Its
existing Perplexity integration covers general web fact-checking, but it does
not provide an explicit X-search capability, and the existing agentic Grok bot
is a coding-session backend rather than a one-shot search service. Treating all
of these as interchangeable tier members would also let automatic routing pick
a backend that has no resumable session.

Users and dispatching agents need two explicit, source-specific search targets
whose answers and citations flow through the normal chat surfaces. The targets
must use xAI's native search tools, remain independent of any other repository,
and fail promptly and visibly instead of leaving a synchronous caller waiting
on a chat that contains no assistant result.

## Solution

Provide two non-agentic inline backends over xAI's native Responses API:
`xai_web` enables the server-side `web_search` tool, and `xai_x` enables the
server-side `x_search` tool. Their conventional bot configurations are
`grok-web` and `grok-x`, respectively. A caller selects the source explicitly by
pinning the appropriate bot or backend; the system never infers the search mode
from query text.

Each invocation sends textual chat input to the selected Responses endpoint,
waits for the one-shot response inside the worker, aggregates assistant text
without assuming output-item order, and publishes URL citations through the
existing message-links contract. Inline completion, post-hooks, unread state,
and Telegram delivery follow one shared lifecycle across xAI, Perplexity, and
OpenAI inline backends. A backend error clears the running state and appends a
visible assistant error so synchronous callers terminate with evidence of the
failure.

The search bots are model-type configurations. They can be reached by an
explicit name or backend pin but are excluded from tier candidacy and therefore
never receive automatic traffic. Those routing semantics remain authoritative
in [Bot Dispatch and Tier Routing](bot-routing.md).

## User Stories

1. As a user, I want a dedicated general-web Grok search bot, so that I can ask
   for current information grounded in web search.
2. As a user, I want a separate X-search Grok bot, so that I can ask about
   current public posts and discussion on X without pretending a web search is
   equivalent.
3. As a user, I want the conventional bot names to be `grok-web` and `grok-x`,
   so that their source and relationship to Grok are clear at the call site.
4. As a dispatching agent, I want to pin either search bot explicitly, so that
   a live-source query bypasses ordinary quality-tier routing.
5. As a dispatching agent, I want to pin `xai_web` or `xai_x` by backend when
   appropriate, so that backend targeting composes with the shared bot resolver.
6. As an admin, I want both search bots classified as model-type entries, so
   that they remain available to explicit pins but never enter automatic tier
   pools.
7. As an admin, I want the two search modes represented by backend identity
   rather than a new database field, so that adding search does not require a
   schema migration or a second configuration mechanism.
8. As a user, I want each backend to activate exactly its named xAI server-side
   search tool, so that the selected source is deterministic.
9. As a user, I want search mode never inferred from my wording, so that an
   ambiguous query cannot silently search the wrong source.
10. As a self-hoster, I want to configure the xAI API key, model, and native API
    base URL through the existing bot configuration surface, so that no new
    secret store or service-specific configuration file is required.
11. As a self-hoster, I want the default xAI endpoint and model to match the
    supported native search service, so that a conventional configuration needs
    only valid credentials.
12. As a user, I want the complete assistant text even when xAI emits reasoning,
    tool-call, and message output items in different orders, so that response
    shape variations do not produce blank or truncated answers.
13. As a user, I want all textual message output segments aggregated in response
    order, so that a response split across segments remains coherent.
14. As a user, I want xAI URL citations exposed through the same message-links
    field used by existing search answers, so that CLI and web references work
    without an xAI-specific presentation path.
15. As a user, I want citation URLs and available titles preserved in response
    order, so that source attribution remains useful and testable.
16. As a user, I want one automatic retry when a search response contains no
    assistant text, so that transient empty X-search results do not immediately
    become blank answers.
17. As a user, I want a second empty response returned as an empty answer rather
    than retried indefinitely or turned into a fabricated result, so that the
    retry policy is bounded and honest.
18. As a synchronous CLI caller, I want an xAI authentication, rate-limit,
    timeout, or response error to produce a visible assistant failure and clear
    the chat's running state, so that `--wait` does not stall until its outer
    timeout with only my prompt visible.
19. As a user, I want successful xAI search completion to participate in the
    same unread-state, post-hook, Telegram, and trace behavior as other inline
    backends, so that changing search providers does not change chat lifecycle
    semantics.
20. As an operator, I want xAI search to run directly in the worker without a VM
    subprocess or resumable agent session, so that a one-shot lookup avoids the
    overhead and misleading continuity of an agentic backend.
21. As a maintainer, I want xAI search implemented independently of
    TradingAgents, so that y-agent may reuse a proven protocol shape without a
    runtime or source dependency on that repository.
22. As a maintainer, I want the xAI call made with the worker's existing HTTP
    stack, so that the deployed packages do not acquire an SDK used only to wrap
    one request.
23. As a maintainer, I want all inline chat backends to share one worker
    lifecycle, so that running-state cleanup, visible failure handling,
    notifications, and post-hooks cannot drift across copy-pasted runners.
24. As an admin editing bot configurations, I want both xAI backend values
    available in the bot management surfaces, so that saving an xAI bot cannot
    erase or replace its backend with an unsupported empty value.
25. As a maintainer without live xAI credentials, I want deterministic parser,
    request-shape, retry, and worker-lifecycle tests to run offline, so that most
    of the contract can be reviewed before credentialed capability verification.
26. As a release operator, I want a credentialed smoke test for each source
    before declaring the corresponding bot operational, so that offline shape
    tests are not mistaken for proof that xAI search is enabled on the account.

## Implementation Decisions

- **Two backend identities define source selection.** `xai_web` always enables
  exactly the native `web_search` tool; `xai_x` always enables exactly the native
  `x_search` tool. There is no query classifier, mode flag, or shared backend
  whose behavior is inferred from the prompt.
- **The conventional bot pair is explicit and readable.** `grok-web` uses
  `xai_web`; `grok-x` uses `xai_x`. Both are model-type, tier3 configurations
  with no routing weight. Tier is descriptive configuration here, not an
  invitation into tier candidacy. The existing agentic `grok` bot is unrelated
  and remains unchanged.
- **Native xAI Responses API only.** Search calls use the configured base URL's
  Responses endpoint. The conventional base URL is `https://api.x.ai/v1`, and
  the conventional model is `grok-4-1-fast`. OpenRouter model aliases are not a
  substitute because they do not expose xAI's server-side web and X tools.
- **Existing bot configuration carries credentials.** A non-empty bot API key
  is required. Base URL and model use the conventional values when absent; a
  caller may override them through the existing fields. No new secret,
  capability, or backend-configuration column is introduced.
- **One request uses one search tool.** The request is non-streaming and carries
  the selected tool as its sole server-side tool. Textual conversation roles are
  translated to the Responses API's typed text input. The feature is optimized
  for a one-shot query; it does not create or resume an xAI-side conversation.
- **Output parsing is structural, not positional.** The parser scans every
  output item, accepts message items, aggregates every `output_text` segment in
  response order, and ignores non-message items such as reasoning and tool
  calls. It never assumes that the first output item is the answer.
- **Citations use the host contract.** Every valid `url_citation` annotation on
  accepted text output becomes an entry in the assistant message's links,
  preserving response order and carrying the URL plus an available title. This
  lets the existing CLI References block and web Sources presentation render
  xAI evidence without provider-specific UI.
- **Empty text has one bounded retry.** The backend repeats the same request once
  when the aggregate assistant text is empty. If the retry is also empty, it
  emits the empty assistant result. Empty text is not treated as transport
  failure, and the backend neither invents fallback prose nor loops again.
- **The request timeout is 180 seconds.** Authentication failures, HTTP errors,
  timeouts, malformed responses, and other exceptions fail the inline run. The
  shared lifecycle clears `running`, appends one assistant error describing the
  backend launch failure, persists it, and re-raises for operational visibility.
- **Inline lifecycle is shared.** Perplexity, OpenAI, `xai_web`, and `xai_x` use
  one worker runner parameterized by message roles and backend callable. It
  validates that the outbound history ends in a user message, runs the backend,
  always clears running state, and on success performs unread marking, Telegram
  delivery, and post-hooks once.
- **Provider identity is xAI.** Successful assistant messages record provider
  `xai`, the resolved model, generated message identity and timestamps, content,
  and optional citation links using the normal Message contract.
- **The deployed worker uses direct HTTP.** The implementation uses the existing
  async HTTP dependency rather than adding the OpenAI SDK to the agent and
  worker deployment solely for the Responses call.
- **The integration is repository-independent.** TradingAgents supplied prior
  evidence for the Responses shape and empty-result retry, but y-agent owns its
  implementation and has no import, package, data, or runtime dependency on
  TradingAgents.
- **Model-type pin behavior belongs to routing.** Explicit name/backend pin
  reachability and exclusion from tier candidacy are specified and tested by
  [Bot Dispatch and Tier Routing](bot-routing.md). This PRD owns the behavior
  after an xAI backend has been selected.

## Testing Decisions

- Test the outbound request at the HTTP boundary: the native Responses endpoint,
  authorization, resolved model, typed textual input, non-streaming shape, and
  exactly one correct tool for each backend value.
- Test backend selection as a two-case contract: `xai_web` produces
  `web_search`, and `xai_x` produces `x_search`. An unsupported xAI backend value
  must not silently choose either source.
- Feed recorded Responses-shaped dictionaries to parser tests. Include output
  where reasoning and tool-call items precede the message, multiple
  `output_text` segments, irrelevant content types, and URL citations with
  titles. Assert aggregate text and citation order rather than helper calls.
- Test empty-result behavior with a mocked HTTP sequence: non-empty first result
  makes one request; empty then non-empty makes two; empty then empty makes
  exactly two and emits an empty assistant message.
- Test configuration validation without live credentials: missing API key,
  custom base URL normalization, default model/base URL, configured model, HTTP
  error, timeout, and malformed response.
- Test the worker lifecycle through shared observable state. Every inline backend
  clears `running`; success appends the provider message and runs completion
  side effects once; failure appends a visible assistant error and does not run
  success post-hooks.
- Keep routing tests in the routing feature: model-type xAI fixtures resolve by
  exact name and backend pins, remain absent from tier candidates, and never win
  an unfiltered dispatch.
- Keep tests offline and deterministic by mocking HTTP responses. Live tests are
  operational smoke checks, not unit-suite prerequisites.
- Before enabling each conventional bot, make one safe credentialed query and
  verify non-empty answer text, at least one source when the query should produce
  citations, the expected persisted bot/backend/provider identity, and prompt
  termination of synchronous wait. Web and X must be verified separately.
- Credential availability alone does not establish live capability. The
  delivery record must not call the bots operational until both credentialed
  smoke checks pass; the credential itself must never appear in tests, docs,
  logs, commits, or callbacks.

## Out of Scope

- Bot candidate resolution, tier policy, route weights, and the general rule
  that model-type bots are pin-reachable but absent from tier candidacy. Those
  belong to [Bot Dispatch and Tier Routing](bot-routing.md).
- Changes to the existing agentic `grok` bot or any attempt to resume an
  agentic Grok session through these inline backends.
- Automatic source selection, combined web-and-X searches, query rewriting, or
  fallback from one source/provider to another.
- xAI-side multi-turn continuation through stored response IDs or other remote
  conversation state.
- Usage or spend accounting for inline backends. The worker currently discards
  inline usage payloads, and Grok subscription credit data is not xAI API-key
  spend accounting.
- Cancellation or live steer during an inline request.
- Image input for inline search chats.
- Citation ranking, independent source verification, or provider-specific
  citation UI beyond the existing message-links presentation.
- Account provisioning, API-key acquisition, xAI billing setup, and automated
  production bot creation without a valid credential.
- A new structured capability field or backend-specific JSON configuration on
  bot configs.
- Any dependency on or change to TradingAgents.

## Delivery Records

| Todo | Outcome | Design | Plan | Decisions | Review | Status |
|------|---------|--------|------|-----------|--------|--------|
| 3206 | Add explicit native xAI web and X inline-search contracts, conventional `grok-web` / `grok-x` model bots, shared inline lifecycle and visible failure handling | - | `pages/plan-3206-grok-search-bots.md` | - | `pages/review-3206-model-pin-routing.md` (routing Deploy A), `pages/review-3206-deploy-b-inline-search.md` (backend Deploy B), `pages/review-3206-bots-module-backend-options.md` (Bots module) | Deploy A shipped; Deploy B and Bots module reviewed; credential available locally, live web/X verification pending |
