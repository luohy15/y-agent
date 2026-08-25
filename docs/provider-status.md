---
title: Provider Status Webhook
category: Operations
order: 6
---

# Provider Status Webhook

The Bot Provider view shows **provider-reported status**, not y-agent's measured
availability. Anthropic is currently the only configured provider. Host storage and
the scheduled reconciliation job normalize the public Claude Status data; the Bot
module reads the bounded host contract.

## Setup

Do not put an endpoint credential in source control, a shell history entry, or a
todo/note. Generate it in the deployment secret store:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Set the generated value as the deployment parameter `AnthropicStatusWebhookSecret`
(which becomes `ANTHROPIC_STATUS_WEBHOOK_SECRET` only inside the API runtime).
After deployment, derive the callback URL without printing the secret to shared logs:

```text
https://<your-api-domain>/api/provider-status/webhook/anthropic/<generated-secret>
```

Then manually open [Claude Status](https://status.claude.com/) and use **Subscribe →
Webhook** to enter that callback and a private failure-notification email. The form
uses reCAPTCHA, so registration is deliberately human-controlled. Do not automate
subscription or unsubscription, and do not store the failure email in y-agent.

### Diagnosing a callback credential mismatch

A `404` with the privacy-safe application warning `invalid endpoint credential` means
the callback path did not exactly match the non-empty runtime credential. It happens
before page or payload validation. Do not troubleshoot it by replaying traffic or by
printing either credential, the callback URL, or a hash that could become a durable
secret identifier.

Compare the runtime credential and the final path segment copied from the Statuspage
subscription privately: read both through hidden prompts, compare their SHA-256 values
in memory with `hmac.compare_digest`, and print only `match=true|false` plus their
lengths. If they differ, determine which side drifted from the intended credential before
making any separately authorized correction. If they match, check URL encoding and
deployment parameter provenance without logging the values. The application never
generates or rotates this credential. Both the GitHub Actions workflow and
`scripts/deploy.sh` must forward the configured secret-store value as
`AnthropicStatusWebhookSecret`; otherwise a manual deploy can drift from the callback
registered with Statuspage.

## Verification boundary and privacy

Claude Status uses Atlassian Statuspage. Its public documentation describes endpoint
verification and incident/component notifications, but does not publish a webhook
signature/HMAC, signing secret, delivery IP list, retry schedule, ordering guarantee,
or payload-size limit. The opaque URL credential is therefore the strongest supported
deployable control. It authenticates possession of the unguessable endpoint, not a
cryptographically signed Anthropic sender.

The receiver accepts only `POST` requests at the exact endpoint, applies a local
256 KiB body cap, uses constant-time secret comparison, validates the canonical Claude
Status page ID and host, and commits the normalized receipt before returning 2xx.
It does not accept an application JWT as webhook authentication. Duplicate and
out-of-order deliveries are retained as bounded, redacted provenance but cannot move
incident or component state backwards.

## Delivery contract and the answer policy

Statuspage requires a `2xx` **within 30 seconds of initial connection**, treats `3xx`
as a failure, and deactivates a subscription that keeps failing. Reactivation is only
possible through the link in the failure email, so any non-2xx answer is an outage of
the whole intake path, not a single lost delivery.

The receiver therefore answers `2xx` to every delivery that proves it came from the
canonical Claude Status page, including a body this normalizer cannot map. Such a body
is stored as a redacted, bounded `unhandled` event and advances
`last_webhook_receipt_at` only: it never sets `last_success_at` and never writes
component or incident state, so an unparsed delivery cannot make stale data look fresh.

Non-2xx answers are reserved for requests that are not authentic provider deliveries:
`404` for a wrong endpoint credential, `413` over the body cap, `400` for a body that
is not JSON, and `422` for a body that is not a JSON object or does not carry the
canonical page identity.

The 30-second budget is bounded end to end: a ~7s worst observed cold start, the 10s
`connect_timeout` in `storage.database.base`, and a 10s `statement_timeout` the
receiver opts into around its single ingest transaction. A database that is down still
answers `5xx` rather than acknowledging data it did not persist; scheduled
reconciliation backfills that window.

## Payload shapes

Two envelope shapes are supported, both taken from Atlassian's published examples and
matched against live deliveries:

- **Component update** — state lives in `component` (`id`, `name`, `status`) and the
  transition in `component_update` (`component_id`, `old_status`, `new_status`,
  `created_at`). `component_update` has **no** `status` field and `component` has no
  `updated_at`, so the component's timestamp falls back to `component_update.created_at`.
- **Incident update** — `incident` plus its embedded `incident_updates`, whose
  `affected_components` may key components by `code` rather than `id`.

Neither shape carries the page's overall status, so a webhook advances component or
incident state and the receipt timestamps but never overwrites the `indicator` and
`description` last set by a Status API poll. Overall health comes from reconciliation
only.

Reading `component_update` as if it were a component is what deactivated the live
subscription on 2026-08-24: every delivery answered `422 invalid component status`,
from the initial connection onward, until Statuspage disabled the endpoint. The
regression lives in `storage/tests/test_provider_status.py`.

## Reconciliation transport

The scheduled worker streams `summary.json` and `incidents.json` so it can enforce a
512 KiB local limit without trusting `Content-Length`. It parses the bytes collected by
that bounded read directly. Do not call `response.json()` after consuming an HTTPX
stream with `aiter_bytes()`: streaming responses do not populate `response.content`, so
that call raises `ResponseNotRead` even though every byte was received.

A successful poll validates the canonical page and advances reconciliation freshness.
A transport, size, JSON, identity, or persistence failure leaves the previous snapshot
and freshness unchanged. The focused transport regression lives in
`worker/tests/test_reconcile_provider_status.py`.

## Re-subscribing after a deactivation

Deactivation is announced by email (and forwarded to Telegram). Re-subscription is
manual, human-gated, and requires explicit approval:

1. Confirm the fix is deployed, then send nothing synthetic to the live endpoint.
2. Open the link in the deactivation email and re-subscribe the same endpoint URL.
3. Watch the API log for `provider status webhook accepted provider=anthropic
   outcome=...`; the endpoint path itself is redacted in access logs.

Raw sanitized webhook provenance is retained for 30 days. Normalized component and
incident history is retained for 366 days. The receiver redacts unsubscribe URLs,
secret/token-like fields, email-like fields, and query-bearing URLs before persistence.

## Freshness and rollback

`last webhook receipt` and `last reconciliation` are deliberately separate. A stale
webhook can coexist with a healthy public-status reconciliation path. Source data is
stale only when neither channel has succeeded recently; silence never means healthy.

To stop intake, remove the subscription from Claude Status or deploy with an unset
secret, then remove or disable the scheduled reconciliation rule as appropriate. This
does not delete normalized historical data. Database DDL lives in
`migration/3266_provider_status.sql` and is manual only: review and apply with `psql`
when separately approved.

## Sources

- [Claude Status API](https://status.claude.com/api)
- [Claude Status](https://status.claude.com/)
- [Atlassian Statuspage webhook subscriptions](https://support.atlassian.com/jira-service-management-cloud/docs/subscribe-to-a-public-status-page-using-webhooks/)
- [Atlassian webhook notifications](https://support.atlassian.com/statuspage/docs/enable-webhook-notifications/)
