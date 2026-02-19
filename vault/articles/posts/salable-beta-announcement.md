---
title: 'Introducing Salable Beta: Build the Pricing Model Your Business Actually Needs'
description: 'Most billing platforms force you to choose: flat-rate or usage-based, per-seat or metered. Salable Beta removes that constraint with composable Line Items that combine any charge types within a single plan.'
publishedAt: 2026-01-27
category: Announcement
author: sean-cooper
tags:
    - product
    - billing
    - beta
draft: false
featured: true
---

# Introducing Salable Beta: Build the Pricing Model Your Business Actually Needs

<!-- IMAGE: Dashboard showing a plan with multiple line items configured
     Placement: hero
     Suggested: Screenshot of Salable Beta's plan configuration with flat-rate, per-seat, and metered components -->

Most billing platforms force you to choose between flat-rate and usage-based billing, and between per-seat and metered billing. Pick one. If your product doesn't fit neatly into a single pricing model, you're left bolting together multiple subscriptions, building custom billing logic, or compromising your charging model. Salable Beta removes that constraint entirely. Today, we're launching a fundamentally different approach to subscription billing—one that lets you combine any charge types you need into a single plan and handle team subscriptions without writing custom code.

## The Problem with "Pick One" Billing

The pricing model that made sense at launch rarely survives contact with real customers. You started with flat-rate monthly subscriptions because they were simple. Then, enterprise customers wanted annual contracts. Then you added a feature that only makes sense to charge by usage. Then, teams needed seat management but also wanted a platform fee.

Traditional billing systems handle each of these individually. They don't handle them together. So you end up managing multiple subscriptions per customer, reconciling charges over different billing cycles, and explaining to confused customers why their invoice has three line items from three different "products" that are really just one product priced three different ways.

The complexity compounds in your codebase. Custom logic to enforce seat limits. Webhook handlers to synchronise subscription states. Edge cases around what happens when someone upgrades one subscription but not the others. Each workaround makes the next change harder.

We built Salable Beta because we kept seeing the same pattern: teams hacking together billing workarounds every time their pricing didn't fit the platform's assumptions, rather than working on features for their core product.

## A Different Architecture

Salable Beta introduces Line Items—composable pricing components that combine within a single plan. Instead of picking one pricing model, you add the charges that reflect how you actually deliver value.

A plan might include a \$99/month platform fee (flat-rate), \$15 per team member (per-seat), \$0.01 per API call (metered), and a \$500 one-time setup charge (one-off). One plan, one subscription, one invoice. Each Line Item appears separately so customers understand exactly what they're paying for.

<!-- IMAGE: Side-by-side comparison showing old approach (multiple subscriptions) vs new approach (single plan with Line Items)
     Placement: inline
     Suggested: Diagram illustrating the architectural simplification -->

Each Line Item type does what you'd expect. Flat-rate charges a fixed amount per billing cycle. Per-seat multiplies by team size. Metered tracks consumption and bills at period end. One-off charges are once at the start and never again. Combine them however your pricing demands.

For products with volume discounts, tiered pricing applies graduated or volume-based rates to any Line Item. The first hundred API calls cost one rate, the next thousand cost less, and enterprise volumes cost less still. The calculation happens automatically—no spreadsheets tracking custom deals, no manual invoice adjustments.

Beyond combining charge types within a plan, subscriptions can contain multiple plans altogether. This enables add-on and plugin pricing systems where customers purchase a core product plus optional extras—an analytics module, API access, premium support—all managed as a single subscription with unified billing. Customers build their own bundle from your catalogue; you don't need to anticipate every combination with pre-built packages.

## Per-Seat Billing Made Easy

Per-seat billing sounds simple until you implement it. Who pays versus who uses isn't the same question. A company admin buys fifty seats; individual team members need access. Managing that relationship typically requires custom membership tables, invitation flows, and seat enforcement logic scattered across your application.

Salable Beta's Grantee Groups model this explicitly. The owner holds the billing relationship. Grantees receive access. Groups manage membership. When you check whether someone can access a feature, you're asking a simple question: Does this grantee have this entitlement? Salable handles the rest.

Seat limits are enforced by the group. The subscription allows fifty seats; the group can have at most fifty grantees. No custom enforcement logic required.

## What We're Looking For

This is a beta. The architecture is solid—we've been running it internally and with early partners. But we want to see it in the hands of real developers solving real pricing problems.

We're looking for developers building SaaS products who've felt the limitations of their billing platforms. You've wanted to charge a base fee plus usage, or combine seat-based licensing with metered features, or offer tiered volume discounts without building custom invoicing. If that sounds familiar, we want you to try Salable Beta and tell us what works and what doesn't.

The feedback loop matters. We're actively developing based on what beta users encounter. Issues you report today shape the features we build tomorrow.

## Getting Started

The beta is open now. Sign up at [beta.salable.app](https://beta.salable.app), connect your Stripe account (test mode works fine for experimentation), and start building. The documentation walks through core concepts, pricing configuration, and integration patterns.

If you're migrating from another billing system—or from Salable's previous version—we're here to help. The architecture is different enough that a fresh look at your pricing model is worthwhile. What compromises did you make because your billing system couldn't handle what you actually wanted to charge? Salable Beta might let you undo those compromises.

We're building the billing infrastructure we wished existed when we were building SaaS products ourselves. Today, you can try it. We're keen to see what you build with it.

---

**Further Reading**

- [Salable Quick Start Guide](https://beta.salable.app/docs/quick-start)
- [Core Concepts Guide](https://beta.salable.app/docs/core-concepts)
- [Products & Pricing Guide](https://beta.salable.app/docs/products-and-pricing)
