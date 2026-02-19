---
title: 'Feature Flags and Entitlements: A Practical Guide'
description: 'Feature flags answer "is this ready?" while entitlements answer "has this user been granted access?" Learn when to use each and how connecting entitlements to subscription state eliminates sync overhead.'
publishedAt: 2026-04-10
category: Insights
author: sean-cooper
tags:
    - entitlements
    - features
    - architecture
    - saas
draft: false
featured: false
---

# Feature Flags and Entitlements: A Practical Guide

<!-- IMAGE: Two parallel tracks labeled "Operational" and "Commercial" converging at a subscription-aware access control point
     Placement: hero
     Suggested: Clean diagram showing feature flags on operational track, entitlements on commercial track, meeting at the application -->

Every SaaS application must answer two questions: "Is this feature ready?" and "Has this user been granted access?" Feature flags answer the first. Entitlements answer the second.

The distinction matters because the tools optimise for different things. Feature flags are operational—they help you control rollouts, run experiments, and kill misbehaving code. Entitlements are commercial—they connect feature access to what customers have paid for. Using one tool for both creates friction that compounds over time: operational concerns tangled with billing logic, access rules scattered across systems, pricing changes that require code deployments.

Understanding what each tool does well is the first step to using them together effectively.

## What Feature Flags Do Well

Feature flags emerged from operational necessity. Engineers needed to deploy code without immediately exposing it to users. Turn the flag on, and the code runs. Turn it off, and it doesn't. Simple, powerful, and entirely about code readiness.

The taxonomy is well-established: release toggles for gradual rollouts, experiment toggles for A/B testing, ops toggles for runtime control, and permission toggles for user access. The first three are clearly operational concerns. The fourth—permission toggles—is where confusion enters.

Large engineering organisations deploy code behind feature flags constantly. Percentage rollouts gradually expose new functionality while monitoring error rates and performance. Instant rollback when problems emerge. Tens of thousands of experiments running simultaneously. Degraded service modes during incidents. These are all operational decisions: is the code ready? Is the system healthy? Should this experiment continue?

The question feature flags answer is: "Is this feature ready?" That's operational, not commercial.

## What Entitlements Do Well

Plans define what customers get. A Pro plan might include analytics, integrations, and priority support. An Enterprise plan adds SSO and audit logs. When someone subscribes to a plan, they get access to those features. When they upgrade, their access expands. When they downgrade or cancel, it contracts.

Entitlements sit between your plans and your application. Your app doesn't check what plan someone is on—it checks whether they have a specific entitlement. The plan grants the entitlement; the app just asks "do they have it?"

This means you can restructure plans without touching code. Move a feature from Pro to Enterprise by updating which plan grants that entitlement. Grandfather existing customers by leaving their entitlement in place even after you change the plan. Create a custom enterprise deal by granting entitlements directly, without inventing a new plan.

## Using Them Together

Both checks can happen on the same feature. The entitlement check asks "does this user have access to analytics?" The feature flag asks "should this user see the new analytics dashboard or the old one?"

Say you're redesigning your analytics dashboard. Users on Pro and Enterprise plans have the analytics entitlement—that doesn't change. But you want to roll out the new design gradually, monitor for problems, and roll back if something breaks. The entitlement controls who can access analytics at all. The feature flag controls which version they see.

The two systems don't overlap. Feature flags never need to know about plans or billing. Entitlements never need to know about rollout percentages or experiments. Each does its job.

## Practical Guidance

How do you know which tool applies to a given access decision?

Ask: "Would this change if the user upgraded their subscription?" If yes, it's an entitlement.

Ask: "Would this change based on deployment state or experiment assignment?" If yes, it's a feature flag.

The grey areas usually resolve when you identify the source of truth. If the answer comes from your billing system, use entitlements. If the answer comes from your deployment pipeline or experiment platform, use feature flags.

## Connecting Entitlements to Billing

The full value of entitlements emerges when they're connected to subscription state automatically. When a customer upgrades, their entitlements expand. When they downgrade, entitlements contract. When they churn, premium access disappears.

Building this yourself means writing webhook handlers for every subscription event, reconciliation jobs for when webhooks fail, and debugging logic for when state drifts. Every payment provider has different webhook schemas and retry semantics. The overhead scales with your pricing complexity.

<!-- IMAGE: Two architecture diagrams side by side: one showing manual sync (webhooks, handlers, reconciliation jobs, state management) and one showing direct entitlement derivation from subscription
     Placement: inline
     Suggested: Left side cluttered with boxes and arrows, right side clean with direct connection -->

## Where Salable Fits

Salable provides the entitlement layer that connects directly to subscription state. Plans grant entitlements. Subscriptions grant plans. When subscription state changes—upgrades, downgrades, renewals, cancellations—entitlements update automatically.

Your application makes a single check: does this user have this entitlement? The answer reflects current subscription state without you having to build webhook handlers, reconciliation jobs, or sync logic.

The operational/commercial distinction stays clean. Use your feature flag platform for rollouts, experiments, and kill switches. Use Salable for everything tied to what customers have paid for. Each system does what it's good at, and the boundary between them is clear.

If you're building subscription software and want pricing flexibility without the access control overhead, [explore Salable's entitlements](https://beta.salable.app/docs/understanding-entitlements).
