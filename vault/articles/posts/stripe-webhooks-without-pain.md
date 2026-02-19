---
title: 'Stripe Webhooks Without the Pain: How Salable Handles the Hard Parts'
description: "Production webhook handling is a reliability engineering problem. Duplicate events, out-of-order delivery, retries, failed event handling—Salable's infrastructure handles these edge cases so you don't debug lost subscriptions at 2 AM."
publishedAt: 2026-02-04
category: Beta Features
author: sean-cooper
tags:
    - webhooks
    - stripe
    - integration
    - reliability
draft: false
featured: false
---

# Stripe Webhooks Without the Pain: How Salable Handles the Hard Parts

<!-- IMAGE: Complex flowchart showing webhook processing pipeline
     Placement: hero
     Suggested: Architecture diagram of multi-stage webhook processing with queues and retries -->

The Stripe webhook documentation makes it look easy: receive an event, verify the signature, process the payload. Three steps. What the documentation doesn't mention is what happens when your server is down during a critical event. Or when the same event arrives twice. Or when a subscription update arrives before the subscription created event. Or when your database transaction fails mid-processing and Stripe retries the webhook while you're in an inconsistent state. Production webhook handling is a reliability engineering problem that most teams underestimate until they're debugging lost subscriptions at 2 AM. Salable's infrastructure handles these edge cases with a battle-tested pipeline that doesn't drop events.

Every developer who's integrated Stripe has a war story. The customer who was charged but never got access because the webhook handler crashed after charging but before provisioning. The duplicate charge that occurred because the handler didn't check for idempotency. The subscription that shows as active in Stripe but cancelled in the application because events arrived out of order. These bugs are insidious because they're intermittent, they affect paying customers, and they're hard to reproduce.

## The Hidden Complexity

Understanding why webhooks are hard requires examining what can go wrong at each stage.

**Network reliability** is the first concern. Stripe sends a webhook; your server receives it; the response returns to Stripe. Any of these network hops can fail. Packets get lost. Connections time out. DNS hiccups. Your server might receive the webhook but Stripe might not receive your acknowledgment, causing a retry of an event you already processed.

**Server availability** matters because webhooks arrive on Stripe's schedule, not yours. A deployment that restarts your application, a spike in traffic that overwhelms your server, or a cloud provider hiccup can all cause missed webhooks. Stripe will retry, but the retry schedule spans hours, and your customers shouldn't wait hours for their purchase to process.

<!-- IMAGE: Timeline showing what happens during server downtime with webhooks
     Placement: diagram
     Suggested: Sequence showing webhook attempts, failures, and eventual delivery -->

**Processing failures** occur even when the webhook arrives successfully. Your handler might throw an exception mid-processing. The database connection might fail during a write. An external API your handler calls might time out. If processing fails after some side effects but before others, you're left in an inconsistent state.

**Duplicate delivery** is explicitly documented by Stripe but often ignored by developers. "Your webhook endpoints might occasionally receive the same event more than once." Occasionally sounds rare, but at scale, occasional adds up. Every handler must be idempotent, treating the second delivery of an event the same as the first.

**Event ordering** can't be guaranteed. A subscription might be deleted before the corresponding creation event arrives. An invoice payment event might arrive before the invoice creation event. Events that seem sequential can arrive in any order, and your handler must cope.

## The Idempotency Requirement

Every webhook handler must be idempotent, meaning processing the same event twice produces the same result as processing it once. This requirement sounds simple but affects how you design every handler.

The naive approach to handling a subscription creation event might be: create a user record, create a subscription record, send a welcome email. If this handler runs twice, you might create duplicate users, duplicate subscriptions, or send duplicate emails. None of these outcomes are acceptable.

The idempotent approach tracks event IDs. Every Stripe webhook carries a unique event identifier, and the first thing a reliable handler does is check whether that identifier has been processed before. If it has, the handler returns success immediately—the work is already done. If the event is new, processing proceeds normally, and the event ID is recorded upon completion. This single check at the event level prevents duplicate users, duplicate subscriptions, and duplicate emails regardless of how many times Stripe delivers the same webhook.

Implementing idempotency correctly requires careful thought about what "already processed" means. An event might have been partially processed before a failure. Your checks need to verify that all effects were applied, not just that processing began.

## Event Ordering Challenges

Stripe sends events in roughly chronological order, but "roughly" isn't a guarantee. Network latency, retry timing, and parallel event generation can all cause events to arrive out of order.

Consider subscription creation and immediate update. A customer creates a subscription and immediately changes a setting. Stripe generates `subscription.created` and then `subscription.updated`. Due to network timing, the update arrives first. Your handler tries to update a subscription that doesn't exist yet, fails, and returns an error. Stripe retries the update later; maybe the creation has processed by then, maybe not.

The robust solution is to read from Stripe's API when processing each event. Instead of relying on the event payload, fetch the current state of the entity directly. That way you always have the latest data regardless of what order events arrive.

<!-- IMAGE: Event sequence showing out-of-order arrival and handling
     Placement: inline
     Suggested: Diagram of events generated in order but arriving out of order -->

## Retry Logic and Exponential Backoff

Stripe retries failed webhooks on an exponential backoff schedule: 5 minutes, 30 minutes, 2 hours, 5 hours, 10 hours, and then hourly for up to 3 days. This schedule means that a server outage lasting an hour might delay event processing for hours, and some events might not be delivered until the next day.

For critical events like subscription creation or payment success, this delay is unacceptable. Customers expect immediate access when they pay. Waiting hours because your server happened to be deploying at the wrong moment is a poor experience.

## Database Transaction Hazards

Webhook handlers often need to update multiple database records together. A subscription creation might create user, subscription, and entitlement records. If any write fails, the entire operation should roll back.

Without transactions, a failure mid-processing leaves your database in a partial state—user created but subscription missing, or subscription created but entitlements not granted. These inconsistencies are difficult to detect and painful to debug. When Stripe retries, your idempotency checks might see existing data and skip steps, leaving the partial state permanently unresolved.

With transactions, all your writes succeed or fail together—but this creates new problems. Long-running transactions hold database connections and block subsequent requests. As handlers queue up, failures cascade—each slow transaction makes the next one slower. Eventually, processing takes longer than Stripe's timeout, and Stripe assumes failure and retries while you're still working on the first attempt.

## Queue-Based Processing

The solution is to separate receipt from processing entirely. When a webhook arrives, your endpoint does three things: validate the signature, write the event to a durable queue, and return success to Stripe. Nothing else. The entire operation takes milliseconds and never touches your main database.

Processing happens separately, driven by workers that pull events from your queue. These workers can take whatever time they need—there's no Stripe timeout looming. If a worker fails mid-processing, the event stays in the queue for another attempt. You control the retry schedule: immediate retries for transient failures, exponential backoff for persistent problems, and configurable limits before giving up. Your transactions can run as long as they need to because they're not blocking Stripe's connection.

This architecture is the right answer, but implementing it yourself is substantial work. You need to choose and operate a queue technology—Redis, RabbitMQ, SQS, or similar—and ensure it's configured for durability so events survive restarts and crashes. You need workers that process reliably, handle failures gracefully, and don't duplicate work when retrying. You need visibility into how full the queue is, how long processing takes, and how often it fails so you can spot problems before customers do. You need alerting when things go wrong and tooling to investigate when they do.

Most teams underestimate this. What starts as "just add a queue" becomes weeks of infrastructure work, and the system requires ongoing operational attention. It's the right architecture, but it's not simple to build or maintain.

## Dead Letter Queues for Failed Events

Some events can't be processed no matter how many times they're retried. An event type your handler doesn't recognise. A payload that fails validation for unknown reasons.

These events shouldn't retry forever. After a configured number of attempts, they should route to a dead letter queue for human review. The queue captures the event payload, the error messages from processing attempts, and timestamps. An operator can examine failed events, determine the cause, fix the underlying issue, and reprocess if appropriate.

<!-- IMAGE: Dashboard showing dead letter queue with event details
     Placement: inline
     Suggested: Admin interface for reviewing and reprocessing failed events -->

Building a dead letter queue isn't complicated, but building the tooling around it—dashboards, alerting, reprocessing workflows—takes time.

## The Alternative

Teams that build their own Stripe integration face a choice: build production-grade webhook handling, or accept the reliability gaps.

Building properly takes weeks of engineering time and ongoing maintenance. For most teams, this is a poor use of engineering resources that could go toward product features.

Accepting reliability gaps means occasional customers who pay but don't get access, subscriptions that fall out of sync between your application and Stripe, and 2 AM debugging sessions when critical events are lost. The cost shows up in support tickets, churn, and engineering distraction.

Salable provides the solution: reliable infrastructure without building it yourself. Your integration stays simple while the hard parts happen behind the scenes.

The Stripe webhook docs make it look easy. Three steps: receive, verify, process. In production, those three steps explode into dozens of edge cases, failure modes, and reliability requirements. Salable handles all of it so you can focus on building your product. Your customers subscribe and get access, every time, without you ever having to debug a lost webhook.
