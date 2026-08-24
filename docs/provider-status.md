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
