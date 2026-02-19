# SaaS Startup Guides: Getting Up and Running

This document contains 8 articles helping SaaS founders and engineering teams implement subscription billing from scratch. The series progresses from basic concepts to advanced operational concerns.

**Content Pillar**: Billing Operations

**Publishing Cadence**: Weekly on Tuesdays, distributed across Weeks 1-4 and 9-12

---

## Articles

### 1. Your First Subscription Product: From Zero to Revenue in an Afternoon

**Synopsis**
Most developers overthink their first billing implementation, spending weeks on edge cases before earning their first dollar. This guide walks through launching a complete subscription product in hours, not weeks, by focusing on the critical path and deferring complexity until you have real customers.

**Lead Intro**
You've built something people want to pay for. Maybe it's a SaaS tool that's been running free while you validated the concept, or perhaps you're starting fresh with a clear monetisation strategy. Either way, you're facing the same question every developer confronts: how do you actually charge people? The billing landscape is littered with engineers who spent months building custom systems, only to discover Stripe's API had evolved while they coded. There's a better path. In the next few hours, you'll have a working subscription product, complete with checkout, entitlements, and payment processing.

**Target Audience**
SaaS Founder

**Key Takeaway**
Launch with a single plan and flat-rate pricing; complexity is a feature you add after customers tell you they need it.

**Salable Hook**
Positions Salable as the fastest path from zero to revenue; promotes Quick Start Guide as proof of simplicity

**Supporting Material**

- [Salable Quick Start Guide](https://beta.salable.app/docs/quick-start)
- [Stripe Billing Quick Start](https://stripe.com/docs/billing/quickstart)
- [Indie Hackers: Revenue Milestones](https://www.indiehackers.com/products)

**Estimated Word Count**: 1,800 words

**Content Pillar**: Billing Operations

---

### 2. Choosing Your First Pricing Model: Flat-Rate vs. Per-Seat vs. Usage-Based

**Synopsis**
The right pricing model depends on how customers derive value from your product. This guide examines the three fundamental models, explaining when each aligns with customer value and how to implement them without over-engineering.

**Lead Intro**
Pricing advice is everywhere, but most of it skips the fundamental question: how do your customers measure the value they get from your product? If they value predictability, flat-rate wins. If value scales with team size, per-seat makes sense. If usage varies wildly between customers, metering aligns your revenue with their outcomes. The model you choose shapes your revenue trajectory, your sales motion, and your engineering requirements. Understanding the tradeoffs now prevents painful migrations later.

**Target Audience**
SaaS Founder

**Key Takeaway**
Choose the model that matches your value metric: flat-rate for tool access, per-seat for collaboration, usage-based for consumption.

**Salable Hook**
Demonstrates expertise in pricing strategy; positions Salable as supporting all three models without lock-in

**Supporting Material**

- [Salable Pricing Models Overview](https://beta.salable.app/docs/products-and-pricing)
- [OpenView: State of Usage-Based Pricing](https://openviewpartners.com/state-of-usage-based-pricing/)
- [Price Intelligently: SaaS Pricing Strategy](https://www.priceintelligently.com/blog/saas-pricing-strategy)

**Estimated Word Count**: 2,200 words

**Content Pillar**: Pricing Mastery

---

### 3. The Entitlements Pattern: Feature Gating That Actually Works

**Synopsis**
Feature flags and pricing tiers shouldn't be separate systems. This guide introduces the entitlements pattern, where subscription plans directly control feature access through named capabilities rather than hardcoded tier checks.

**Lead Intro**
Your codebase is full of checks like `if (user.plan === 'pro')` scattered across dozens of files. Adding a new tier means hunting down every comparison and hoping you didn't miss one. Worse, your feature flags and your billing tiers have drifted apart, so customers on the "Pro" plan might not have access to features you thought were included. The entitlements pattern fixes this by making plans grant named capabilities rather than rely on tier matching. Your code checks for `can_export_pdf` instead of `plan === 'pro'`, and the mapping from plans to capabilities lives in your billing configuration, not your codebase.

**Target Audience**
Engineering Lead

**Key Takeaway**
Check for capabilities, not tiers; `user.hasEntitlement('advanced_analytics')` survives pricing changes that `user.plan === 'pro'` cannot.

**Salable Hook**
Promotes Salable's entitlements system as core differentiator; positions as solving feature gating pain that DIY approaches create

**Supporting Material**

- [Salable Entitlements Guide](https://beta.salable.app/docs/understanding-entitlements)
- [LaunchDarkly: Feature Flags Best Practices](https://launchdarkly.com/blog/best-practices-for-feature-flags/)
- [Martin Fowler: Feature Toggles](https://martinfowler.com/articles/feature-toggles.html)

**Estimated Word Count**: 2,000 words

**Content Pillar**: Billing Operations

---

### 4. Team Subscriptions: When One Seat Isn't Enough

**Synopsis**
Moving from individual to team subscriptions introduces complexity around seat management, billing ownership, and access control. This guide covers the key decisions and implementation patterns for multi-user subscriptions.

**Lead Intro**
Your first customers were individuals, and per-user billing was straightforward. But now a company wants to buy seats for their whole team, and suddenly simple questions get complicated. Who receives the invoice: the person who signed up or their finance department? How do team members get access without sharing credentials? What happens when someone leaves the team mid-billing-cycle? Team subscriptions aren't just per-seat pricing multiplied out. They're a different model with distinct concepts: billing owners versus users, seat allocation and limits, and organisational access control.

**Target Audience**
SaaS Founder

**Key Takeaway**
Separate the billing relationship (who pays) from access grants (who uses); this distinction simplifies both your code and your customers' administrative experience.

**Salable Hook**
Promotes Salable's grantee groups and owner/grantee model; positions as solving team billing complexity out of the box

**Supporting Material**

- [Salable Grantee Groups Guide](https://beta.salable.app/docs/grantee-groups)
- [Stripe Team Subscriptions](https://stripe.com/docs/billing/subscriptions/multiparty)
- [SaaStr: Seat-Based Pricing](https://www.saastr.com/seat-based-pricing/)

**Estimated Word Count**: 1,800 words

**Content Pillar**: Billing Operations

---

### 5. Handling Failed Payments Without Losing Customers

**Synopsis**
Payment failures are inevitable, but customer churn from failed payments isn't. This guide covers dunning strategies, retry logic, grace periods, and communication patterns that recover revenue without alienating customers.

**Lead Intro**
Somewhere in your customer base, a credit card is about to expire. Another customer's payment will decline because they hit their limit buying holiday gifts. A third will fail because their bank's fraud detection flagged an unfamiliar charge. These aren't edge cases; payment failures affect 5-10% of subscription charges every month. The difference between recovering that revenue and losing those customers comes down to how you handle the failure. Aggressive dunning annoys customers, while passive approaches let subscriptions lapse silently. The right strategy balances persistence with respect.

**Target Audience**
SaaS Founder

**Key Takeaway**
Combine automated retries with proactive customer communication; smart retry timing recovers 30-50% of failed payments before customers even notice.

**Salable Hook**
Demonstrates expertise in billing operations; positions Salable + Stripe as handling recovery automatically

**Supporting Material**

- [Stripe Smart Retries](https://stripe.com/docs/billing/revenue-recovery/smart-retries)
- [ProfitWell: Dunning Best Practices](https://www.profitwell.com/recur/all/dunning)
- [Baremetrics: Failed Payment Recovery](https://baremetrics.com/blog/recover-failed-payments)

**Estimated Word Count**: 1,600 words

**Content Pillar**: Billing Operations

---

### 6. Testing Your Billing Integration Before It Costs You

**Synopsis**
Billing bugs are expensive. This guide covers testing strategies for subscription systems: test mode environments, synthetic scenarios, edge case coverage, and the minimum test suite every billing integration needs.

**Lead Intro**
Your billing code will run exactly once per customer per event. There's no retry, no rollback, no "let's deploy a fix and re-run." If the webhook handler fails to provision access, customers wait on support. If the upgrade flow double-charges, you're issuing refunds and apologies. The usual development instincts, deploy fast and iterate, don't apply when money is involved. Testing billing integrations requires different strategies: isolated test environments, synthetic customer lifecycles, and explicit coverage of edge cases that production will inevitably generate.

**Target Audience**
Engineering Lead

**Key Takeaway**
Test the complete customer lifecycle in test mode: signup, upgrade, downgrade, payment failure, and cancellation are not independent flows.

**Salable Hook**
Promotes Salable's test mode environment; positions as reducing billing integration risk

**Supporting Material**

- [Stripe Test Mode Guide](https://stripe.com/docs/testing)
- [Salable Test Mode Documentation](https://beta.salable.app/docs/quick-start#test-mode)
- [Test Double: Testing Third-Party Integrations](https://blog.testdouble.com/posts/2018-03-06-testing-external-services/)

**Estimated Word Count**: 2,000 words

**Content Pillar**: Billing Operations

---

### 7. Webhooks: Keeping Your App in Sync with Billing Events

**Synopsis**
Webhooks are the nervous system of billing integration, but implementing them reliably requires attention to ordering, idempotency, and failure handling. This guide covers the patterns that prevent missed events and duplicate processing.

**Lead Intro**
Your application needs to know when subscriptions change, but polling the billing API every minute is wasteful and slow. Webhooks deliver events in real-time, but they come with their own challenges. Events can arrive out of order. Your server might be down when a critical event fires. The same event might be delivered twice. Building reliable webhook handling means accounting for these realities rather than assuming perfect delivery. The patterns aren't complicated, but they're non-obvious to developers who haven't been burned by production failures.

**Target Audience**
Engineering Lead

**Key Takeaway**
Make webhook handlers idempotent from day one; implementing idempotency later requires migrating your entire event history.

**Salable Hook**
Promotes Salable's webhook system with delivery guarantees and retry logic; demonstrates technical depth

**Supporting Material**

- [Salable Webhooks Guide](https://beta.salable.app/docs/webhooks)
- [Stripe Webhook Best Practices](https://stripe.com/docs/webhooks/best-practices)
- [Hookdeck: Webhook Reliability](https://hookdeck.com/webhooks/guides/webhook-reliability-best-practices)

**Estimated Word Count**: 2,200 words

**Content Pillar**: Billing Operations

---

### 8. The Build vs. Buy Decision: When DIY Billing Makes Sense

**Synopsis**
Building billing in-house is tempting but rarely justified. This guide provides a framework for evaluating build versus buy, covering hidden costs, maintenance burden, and the scenarios where custom implementation actually makes sense.

**Lead Intro**
"We'll just use Stripe directly" is one of the most expensive decisions a startup can make. Not because Stripe is hard to integrate, but because billing is an iceberg: the checkout flow is the visible 10%, while subscription management, failed payment handling, usage metering, entitlement enforcement, and tax compliance lurk beneath the surface. Teams that start with DIY billing inevitably discover these hidden requirements, usually after shipping a fragile v1 that becomes increasingly expensive to maintain. Understanding when build makes sense requires honest accounting of both immediate and ongoing costs.

**Target Audience**
SaaS Founder

**Key Takeaway**
Build if billing is your competitive advantage; buy if it's infrastructure that should fade into the background while you focus on your actual product.

**Salable Hook**
Directly positions Salable as the "buy" answer; makes the case for platform over DIY with Salable as the solution

**Supporting Material**

- [Salable Core Concepts](https://beta.salable.app/docs/core-concepts)
- [a]16z: The Billing Complexity Cliff](https://a16z.com/the-saas-billing-cliff/)
- [Indie Hackers: DIY vs Platform Billing](https://www.indiehackers.com/post/build-vs-buy-billing)

**Estimated Word Count**: 2,000 words

**Content Pillar**: Billing Operations

---

## Series Summary

These eight articles provide a complete curriculum for SaaS billing implementation:

| Article                     | Stage           | Key Decision                    |
| --------------------------- | --------------- | ------------------------------- |
| First Subscription Product  | Getting Started | Launch quickly, iterate later   |
| Choosing Your Pricing Model | Foundation      | Match model to value delivery   |
| The Entitlements Pattern    | Architecture    | Capabilities over tier checks   |
| Team Subscriptions          | Scaling         | Ownership versus access         |
| Failed Payment Handling     | Operations      | Recovery versus churn           |
| Testing Billing             | Quality         | Complete lifecycle coverage     |
| Webhooks                    | Integration     | Idempotency and reliability     |
| Build vs. Buy               | Strategy        | Infrastructure versus advantage |

The series progresses from tactical implementation to strategic decisions, matching the journey most SaaS founders take as their billing requirements mature.
