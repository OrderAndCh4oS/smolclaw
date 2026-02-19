---
title: 'Webhooks: Real-Time Billing Events for Your Application'
description: 'Stop polling for subscription changes. Webhooks notify your application the moment something happens, from subscription creation to payment failure.'
publishedAt: 2026-02-13
category: Beta Features
author: sean-cooper
tags:
    - webhooks
    - integration
    - features
    - billing
draft: false
featured: false
---

# Webhooks: Real-Time Billing Events for Your Application

<!-- IMAGE: Diagram showing events flowing from billing system to application
     Placement: hero
     Suggested: Visual of webhook events (subscription.created, payment.failed) reaching an application -->

Your customer just upgraded their plan, but your application still shows them the old features. Maybe your cron job will catch it in an hour. Maybe tomorrow. Polling for subscription changes works until it doesn't, and when it fails, customers notice. Webhooks flip the model. Instead of asking "has anything changed?" every few minutes, your application receives a notification the moment a change occurs. Subscription created, payment failed, usage recorded: your system knows immediately. The customer upgrades at 2:47 PM, and by 2:47 PM their new features are live.

The polling approach seemed reasonable when you built it. Every fifteen minutes, your background job queries the billing API for subscriptions modified since the last check. It processes any changes, updates your local database, and goes back to sleep. The simplicity was appealing, and for low volumes it worked fine.

Then you scaled. The fifteen-minute window started feeling long when customers complained about delayed access. You shortened it to five minutes, then one minute. Now your job runs constantly, making API calls that usually return empty results. Your rate limits are stressed. Your billing API costs increased. And the fundamental problem remained: customers still waited up to a minute for changes to propagate.

Webhooks eliminate this latency entirely. The billing system pushes events to your application as they occur. The upgrade happens, the event fires, your handler runs, and the features unlock. The delay drops from minutes to milliseconds.

## The Event-Driven Model

Understanding webhooks requires shifting from pull to push thinking. In the polling model, your application is the active party, asking the billing system for updates on a schedule you control. In the webhook model, the billing system is the active party, pushing updates to an endpoint you've registered.

This inversion has profound implications for how you architect your application. Polling code typically lives in a scheduled job that reads data and updates state. Webhook code lives in an HTTP handler that receives data and updates state. The logic is similar, but the trigger is different.

<!-- IMAGE: Comparison of polling vs webhook architectures
     Placement: diagram
     Suggested: Side-by-side showing pull loop vs push notification flow -->

Webhooks arrive as HTTP POST requests to an endpoint you specify. The request body contains a JSON payload describing what happened: the event type, the relevant objects (subscription, invoice, customer), and timestamps. Your handler parses the payload, validates that it's legitimate, and processes the event.

The key mental model is that webhooks are facts about things that happened. "Subscription SUB-123 was upgraded to Professional plan at 14:47:23 UTC." Your handler's job is to update your system's state to reflect this fact. The subscription in your database should now show Professional plan. The customer's entitlements should reflect Professional features.

## Event Types That Matter

Salable sends webhooks for all significant billing events. Knowing which events to handle lets you build responsive applications that stay synchronised with billing state.

**Subscription lifecycle events** tell you when subscriptions are created, updated, or cancelled. A new subscription means a new customer to provision. An updated subscription might mean changed entitlements or seat counts. A cancelled subscription means access should end at the appropriate time.

**Payment events** inform you about billing success and failure. A successful payment confirms continued access. A failed payment might trigger a grace period or dunning flow. A dispute or refund might require special handling depending on your policies.

**Invoice events** track the billing document lifecycle. An invoice created event lets you add custom line items before finalization. An invoice paid event confirms payment processing. An invoice past due event might trigger account restrictions.

**Usage events** for metered billing confirm that usage records were received and will be included in the next invoice. These events provide an audit trail and let you verify that your usage reporting is being processed correctly.

Each event type has a defined payload structure documented in Salable's webhook reference. The structure includes the event type identifier, a timestamp, and the relevant objects with their current state.

## Building a Robust Webhook Handler

A production webhook handler needs more than a simple HTTP endpoint. Several concerns require careful implementation to ensure reliability.

**Signature verification** ensures that webhooks actually came from Salable and weren't forged by attackers. Each webhook includes a signature header computed from the payload and a secret key. Your handler must verify this signature before processing. Salable's SDKs include signature verification functions, so you don't need to implement the cryptography yourself.

```javascript
const isValid = salable.webhooks.verify(payload, signatureHeader, webhookSecret);

if (!isValid) {
    return res.status(401).send('Invalid signature');
}
```

**Idempotent processing** handles the case where the same event arrives multiple times. Network issues, retries, and edge cases can cause duplicate delivery. Your handler should process each event exactly once, even if it's received multiple times. Typically this means checking whether you've already processed an event ID before taking action.

<!-- IMAGE: Flowchart of webhook handler with verification and idempotency checks
     Placement: diagram
     Suggested: Decision tree showing the webhook processing pipeline -->

**Response timing** matters because webhook delivery systems expect quick responses. Your handler should acknowledge receipt by returning a 200 status code promptly, ideally within a few seconds. If your processing takes longer, acknowledge first and process asynchronously. A handler that times out will cause retries and potential duplicate processing.

**Error handling** determines what happens when processing fails. Return a 5xx status code to signal that Salable should retry the webhook. Return a 4xx status code if the webhook itself is malformed and retries won't help. Log errors with enough context to debug later.

## Handling Common Event Patterns

Certain event sequences appear repeatedly across applications. Understanding these patterns helps you implement correct handling.

**Subscription creation** typically triggers user provisioning. When you receive a `subscription.created` event, you might create a workspace for the customer, initialize their settings, send a welcome email, and update your customer database. The order of these operations might matter; ensure the workspace exists before sending an email with a link to it.

**Subscription upgrade** means entitlement changes. The customer's old features should continue working while new features become available. Check the `previousAttributes` field in the event payload to see what changed, and update your entitlement cache accordingly.

**Payment failure** starts a grace period in most applications. The customer's access continues temporarily while you attempt to collect payment. Send notifications encouraging them to update their payment method. After a configured number of retries or days, a follow-up event indicates whether payment succeeded or the subscription should be suspended.

**Subscription cancellation** has immediate and scheduled variants. An immediate cancellation means access ends now. A scheduled cancellation (at period end) means access continues until the paid period expires. Your handler should check the cancellation timing and act appropriately.

## Testing Webhook Handlers

Webhook handlers are notoriously difficult to test because they receive external events that are hard to simulate. Several strategies make testing tractable.

**Local testing** with webhook forwarding lets you receive real webhooks on your development machine. Tools like ngrok or Cloudflare Tunnel expose your localhost to the internet, giving you a public URL to configure as your webhook endpoint. This lets you trigger real events and see how your handler responds without deploying to a server.

**Payload capture** during local development gives you test fixtures. Log the raw payloads your handler receives, then save representative examples as JSON files. Replay these in unit tests to verify your parsing, validation, and processing logic without network dependencies.

**Integration tests** in staging environments verify the full flow. Create a test subscription, observe the webhook arrive, verify your handler processed it correctly. Automate these tests to run on deployment.

**Monitoring in production** catches issues that testing misses. Track webhook reception rates, processing times, and error rates. Alert on anomalies like sudden drops in events or spikes in errors. The sooner you notice a problem, the sooner you can fix it.

## Webhook Reliability and Retries

Network failures happen. Servers go down. Bugs cause handlers to crash. A robust webhook system handles these failures gracefully.

Salable's webhook delivery includes automatic retries with exponential backoff. If your handler returns an error or times out, the webhook is retried after a delay. The delay increases with each retry, preventing retry storms from overwhelming a struggling server.

The retry schedule follows a pattern: immediate retry, then one minute, five minutes, thirty minutes, two hours, and so on up to a configurable maximum. Most transient failures resolve within the first few retries. Persistent failures eventually stop retrying, and the event moves to a dead letter queue for manual investigation.

Your handler should be idempotent to handle retries gracefully. If the first attempt partially succeeded before failing, the retry shouldn't double-count the action. Check whether the event was already processed, or design your operations to be naturally idempotent (setting state rather than incrementing counters).

<!-- IMAGE: Timeline showing retry schedule with exponential backoff
     Placement: inline
     Suggested: Visual of retry attempts over time with increasing gaps -->

## Monitoring and Debugging

Webhook-driven architectures require visibility into the event flow. When something goes wrong, you need to understand what events arrived, how they were processed, and what state resulted.

**Logging every event** provides an audit trail. Log the event type, relevant IDs, timestamp, and processing outcome. When investigating an issue, you can trace from a customer complaint to the events that should have fired to how your handler processed them.

**Monitoring delivery health** catches systemic issues. Track the volume of webhooks received over time. A sudden drop might indicate a configuration problem or Salable infrastructure issue. A sudden spike might indicate unusual activity worth investigating.

**Dashboard visibility** through Salable's interface shows recent webhooks, their delivery status, and response codes from your handler. When debugging, you can see exactly what was sent and whether your endpoint acknowledged receipt.

**Alert on failures** to catch problems before customers report them. If your handler starts returning errors, you want to know immediately. Configure alerts for error rate thresholds so you can investigate and fix issues proactively.

## Moving Beyond Polling

Migrating from polling to webhooks typically happens incrementally. You add webhook handlers alongside existing polling, verify they work correctly, then remove the polling once you trust the new system.

During the transition, reconciliation jobs help catch discrepancies. Run a periodic job that compares your local state against the billing API. Any differences indicate either a missed webhook or a handler bug. As your webhook handling matures, these reconciliation runs should find fewer issues until you're confident enough to remove them.

The operational benefits of webhooks compound over time. Lower API usage reduces costs. Faster propagation improves customer experience. Event-driven architecture enables real-time features that polling can't support. The initial investment in building robust handlers pays dividends in everything built on top of them.

## Real-Time Applications

Webhooks enable application patterns that aren't possible with polling.

**Instant feature unlocks** let customers use new features the moment they pay. No more "your access will be updated within the hour" messages. The upgrade event fires, your handler runs, and the feature is live.

**Payment failure responses** can be immediate and contextual. Instead of a batch email hours later, you can show an in-app notification the moment payment fails. "We couldn't charge your card, click here to update" appears while the customer is actively using your product.

**Usage dashboards** can update in real-time as metered events are recorded. The customer watches their usage count increment with each API call, building confidence that billing will be accurate.

**Automated workflows** trigger on billing events without delay. A new subscription could kick off an onboarding sequence. A cancellation could trigger a feedback survey. A payment failure could assign a task to your success team. The speed of webhooks makes these workflows feel automatic rather than batched.

Your billing system becomes a real-time data source rather than a database you periodically sync. Events flow through your application as they happen, keeping every system aligned without manual intervention or scheduled jobs. The customer upgraded at 2:47 PM, and by 2:47 PM everything in your application reflects that upgrade. That's the power of webhooks.
