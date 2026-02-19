---
title: 'Webhooks: Keeping Your App in Sync with Billing Events'
description: 'Polling the billing API every minute is wasteful and slow. Webhooks deliver events in real-time, but they come with challenges: out-of-order delivery, server downtime, duplicates.'
publishedAt: 2026-03-31
category: SaaS Startup Guides
author: sean-cooper
tags:
    - webhooks
    - integration
    - billing
    - architecture
draft: false
featured: false
---

Your application needs to know when subscriptions change, but polling the billing API every minute is wasteful and slow. Webhooks deliver events in real-time, but they come with their own challenges. Events can arrive out of order. Your server might be down when a critical event fires. The same event might be delivered twice.

Building reliable webhook handling means accounting for these realities rather than assuming perfect delivery. The patterns aren't complicated, but they're non-obvious to developers who haven't been burned by production failures.

<!-- IMAGE: Diagram showing webhook flow from billing system to application
     Placement: hero
     Suggested: Architectural diagram with event flow arrows -->

## The Webhook Mental Model

Think of webhooks as push notifications for your server. Instead of your application constantly asking "did anything change?" the billing system sends a message when something happens. This approach is more efficient and delivers faster updates, but it requires your application to be ready to receive messages at any time.

When a billing event occurs—a successful payment, a subscription cancellation, or a plan change—the billing system generates a payload describing the event and sends an HTTP request to an endpoint you've configured. Your application receives this request, processes the event, and responds to acknowledge receipt.

That simple flow, however, masks several challenges. Your endpoint must be publicly accessible, which means you need to validate that requests actually come from the billing system rather than from attackers. Your processing must handle the same event arriving multiple times. Your application must remain functional even when events arrive in unexpected orders. Each of these concerns requires explicit engineering attention.

The alternative to webhooks is polling, where your application periodically requests the current state of subscriptions and compares it to what you've stored. Polling works but has significant drawbacks. The interval between polls creates latency; a customer who upgrades won't see their new features until the next poll completes. Frequent polling wastes resources and may hit rate limits. Infrequent polling delays important changes. Webhooks solve these problems by delivering updates immediately, but they shift complexity from timing to reliability.

## Validating Webhook Authenticity

Anyone who discovers your webhook endpoint can send requests to it. Without validation, an attacker could fabricate events to manipulate your application's billing state. Signature validation prevents this by cryptographically proving that requests originated from the billing system.

Each webhook request includes a signature, typically in a header. The signature is computed using a secret key shared between you and the billing system. Your handler computes the expected signature from the request body and shared secret, then compares it to the provided signature. If they match, the request is authentic. If they don't, reject the request.

<!-- IMAGE: Diagram showing signature computation and validation flow
     Placement: diagram
     Suggested: Security-focused illustration with lock icons and comparison -->

The signature computation typically involves a cryptographic hash function like HMAC-SHA256. Your billing provider's documentation specifies the exact algorithm. Most webhook libraries and SDKs include signature validation functions; use them rather than implementing your own. Cryptographic code is easy to get subtly wrong.

Store your webhook secret securely. It should be treated like a password: not committed to source control, not logged, and rotated if potentially compromised. If an attacker obtains your webhook secret, they can forge valid webhook requests.

Some billing systems timestamp their signatures to prevent replay attacks, where an attacker captures a valid webhook and resends it later. Your validation should check the timestamp and reject requests older than a reasonable threshold, typically a few minutes.

## The Idempotency Imperative

The billing system may deliver the same webhook multiple times. This isn't a bug; it's a feature of reliable delivery. When acknowledgment of delivery fails to arrive—perhaps your server responded slowly, or a network issue dropped the response—the system retries. Your handler must produce the same outcome whether it processes an event once or ten times.

This property is called idempotency, and it's the single most important principle in webhook handling. An idempotent handler can be safely called multiple times without changing the result beyond the first call. Designing for idempotency from the start is vastly easier than retrofitting it later—adding idempotency to an existing system often means migrating your entire event history.

The standard approach uses an event identifier. Each webhook includes a unique ID for the event it represents. Before processing, your handler checks whether you've already processed this event ID. If you have, skip processing and return success. If you haven't, process the event and record the ID.

This check-then-process pattern has a race condition: two concurrent deliveries of the same event might both pass the check before either records the ID. Use database constraints or transactions to ensure atomicity. A unique constraint on the event ID column converts the race condition into a constraint violation, which you handle by returning success.

Idempotency extends beyond duplicate detection. Your processing logic itself should be idempotent. If a webhook grants a user entitlements, granting them again should be safe (they already have them). If a webhook updates subscription status, updating to the same status should be a no-op. Design your handlers so that the entire operation, not just the delivery, is idempotent.

## Handling Out-of-Order Delivery

Webhooks don't necessarily arrive in the order events occurred. A subscription update might arrive before the subscription created event. A payment succeeded notification might arrive after a payment failed notification for an earlier retry. Your handlers must be robust to these ordering variations.

The root cause is that webhooks operate in a distributed system. Different events might be processed by different servers, routed through different network paths, and delivered on different retry schedules. Even if event A happened before event B, the webhook for B might arrive first.

<!-- IMAGE: Timeline showing events in occurrence order vs delivery order
     Placement: inline
     Suggested: Parallel timelines showing reordering -->

The safest pattern is to fetch current state rather than relying on the webhook content. When you receive a webhook indicating that subscription status changed, don't trust the status in the payload. Instead, use the webhook as a signal to fetch the subscription's current state from the billing API. The API always returns current truth; the webhook payload might be stale.

This pattern trades API calls for correctness. Each webhook triggers a fetch, which adds latency and API usage. For most applications, the tradeoff is worthwhile. If API costs or latency become significant concerns, you can optimise by trusting webhook data for create events (where there's no previous state to conflict with) while fetching for updates.

Some systems include timestamps or version numbers in webhook payloads. You can compare the webhook's timestamp against your stored timestamp, only applying updates if the webhook is newer. This approach works but requires careful handling of clock skew and initial state.

## Failure Handling and Retries

Your webhook endpoint might be unavailable when an event fires. Your server might crash, your network might hiccup, or your handler might throw an exception. The billing system will retry delivery, but your application needs to cooperate with that retry mechanism.

Return appropriate HTTP status codes. A 200-level response signals that you've received and processed the event; no retry follows. A 500-level response signals that something went wrong; the billing system will retry later. A 400-level response typically indicates a malformed request; whether a retry occurs depends on the specific code and billing system.

Process webhooks quickly. Most billing systems enforce timeout thresholds; if your handler takes too long, the delivery is treated as a failure and retried. If your processing is inherently slow, acknowledge receipt immediately and process asynchronously.

Asynchronous processing requires its own reliability layer. If your server crashes after acknowledging but before processing, the billing system considers delivery complete, but you've lost the event. You need a queue or similar mechanism to ensure processing completes. The added complexity is manageable but non-trivial.

## Monitoring and Alerting

Webhooks fail silently from your perspective. If your endpoint is down, you won't receive notifications about the missed notifications. Monitoring must be proactive rather than reactive.

Track webhook receipt rate. You should receive webhooks at a relatively consistent rate, proportional to your activity. A sudden drop might indicate endpoint problems, misconfiguration, or issues on the billing provider's side. A sudden spike might indicate test data accidentally routed to production, or an attack.

Monitor handler success rate. Track how many webhooks process successfully versus fail with exceptions. A rising error rate indicates bugs in your handling code or unexpected payload variations.

<!-- IMAGE: Monitoring dashboard showing webhook metrics
     Placement: inline
     Suggested: Dashboard-style illustration with graphs and alerts -->

Set up alerts for missing expected webhooks. If you process a checkout event but never receive the corresponding subscription created event, something is wrong. Reconciliation alerts like these catch issues that receipt monitoring misses.

Log webhook payloads for debugging. When handling fails, you need to understand what the payload contained. Logging should be detailed enough to reproduce issues but careful about sensitive data. Redact payment method details and personally identifiable information from logs.

Periodically reconcile your state against the billing system's state. Even with perfect webhook handling, you might have historical bugs or missed events from before monitoring was in place. A weekly job that fetches all subscriptions and compares them against your database catches drift before it causes customer impact.

## Scaling Webhook Processing

As your customer base grows, webhook volume increases. A system that handled ten webhooks per minute might suddenly need to handle hundreds. Your architecture needs to scale with demand.

Queue-based processing decouples receipt from handling. Your webhook endpoint validates the signature, enqueues the event, and returns immediately. Separate workers pull from the queue and process events. This architecture handles traffic spikes gracefully: the queue absorbs bursts while workers process at sustainable rates.

Horizontal scaling adds more workers as volume increases. If one worker can process fifty webhooks per second, ten workers can process five hundred. Queue-based architectures make scaling straightforward: you add workers without changing the receipt endpoint.

Database write patterns may become bottlenecks before processing speed does. Every webhook that updates subscription state writes to your database. If many webhooks arrive simultaneously for the same subscription, you'll either serialise writes (slowing processing) or risk consistency issues from concurrent updates. Batching writes or using optimistic concurrency control helps manage this contention.

Consider geographic distribution for latency. If webhooks are delivered from a specific region and your servers are far away, network latency adds to processing time. Multi-region deployment or edge processing can reduce this latency for customers sensitive to synchronisation speed.

---

Getting webhooks right is harder than it looks. Many devs patch together something "good enough" and move on, only to discover missed events and silent failures months later when customers complain. Building infrastructure that never misses a webhook takes serious effort—and maintaining it takes more.

Salable handles all subscription lifecycle webhooks internally. Payments, cancellations, upgrades, renewals—we process them so you don't have to. Your entitlements stay in sync without you writing a single webhook handler.

If you want to respond to events for your own purposes—notifications, alerts, setting up account data—you can use our [webhook events](https://beta.salable.app/docs/webhooks). But for most apps, it's entirely optional.
