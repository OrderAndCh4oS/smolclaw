# Insights: Expert Positioning Articles

This document contains 7 articles positioning Salable as a thought leader in subscription pricing and billing strategy. These articles take strong positions, challenge conventional wisdom, and provide strategic frameworks rather than tactical how-tos.

**Content Pillar**: Pricing Mastery

**Publishing Cadence**: Distributed across Weeks 1-8, primarily on Fridays

---

## Articles

### 1. The Hidden Cost of "Simple" Pricing

**Synopsis**
Founders chase pricing simplicity, but oversimplified pricing often leaves money on the table. This article argues that the real cost isn't complexity, it's misalignment between pricing and value, and provides a framework for finding the right level of pricing sophistication.

**Lead Intro**
"Keep it simple" is sound pricing advice—especially when you're starting out. The single $9/month plan has real appeal: no tiers to agonise over, no usage tracking to implement, no decisions for customers to make. It gets you to revenue fast, and there's genuine wisdom in that. But simple pricing that works at launch rarely stays optimal as you grow. A flat rate that felt fair to your first hundred customers starts leaving money on the table once you're serving enterprises alongside hobbyists. The question isn't whether to start simple—you probably should. It's knowing when simple stops serving you, and what the minimum complexity looks like that actually captures the value you create.

**Target Audience**
SaaS Founder

**Key Takeaway**
The goal isn't pricing simplicity, it's pricing clarity; a three-tier structure that maps to real customer segments is clearer than a single price that fits no one well.

**Salable Hook**
Demonstrates expertise in pricing strategy; positions Salable as enabling pricing sophistication without engineering complexity

**Supporting Material**

- [Price Intelligently: Pricing Strategy Guide](https://www.priceintelligently.com/blog/saas-pricing-strategy)
- [Patrick Campbell: Value-Based Pricing](https://www.profitwell.com/recur/all/value-based-pricing)
- [Salable Products and Pricing](https://beta.salable.app/docs/products-and-pricing)

**Estimated Word Count**: 2,000 words

**Content Pillar**: Pricing Mastery

---

### 2. Why Your Pricing Page Is Losing You Customers

**Synopsis**
Most SaaS pricing pages fail because they're organised around features rather than customer outcomes. This article deconstructs common pricing page mistakes and provides principles for pages that convert.

**Lead Intro**
Pricing pages are high-stakes real estate. Visitors who reach your pricing page have significantly higher conversion intent than average—they're actively evaluating whether to buy. Yet many pricing pages squander this opportunity. The typical SaaS pricing page commits the same sins: feature comparison tables that read like spec sheets, tier names that mean nothing, and a sea of checkmarks that blur together. Customers land on pricing pages with a question: "Is this right for me?" Feature matrices don't answer that question. They answer "What do I get?"—which is a different, less important inquiry. Fixing pricing pages requires shifting from features to outcomes, from comparison to recommendation.

**Target Audience**
Product Manager

**Key Takeaway**
Lead with outcomes, not features; "For teams shipping weekly" tells customers more than "Unlimited deployments" ever could.

**Salable Hook**
Demonstrates expertise in pricing psychology; builds trust as pricing advisors, not just billing infrastructure

**Supporting Material**

- [Nielsen Norman Group: Comparison Tables](https://www.nngroup.com/articles/comparison-tables/)
- [CXL: Pricing Plan Order Study](https://cxl.com/research-study/pricing-plan-study-order/)
- [Profitwell: Pricing Page Visitors](https://userpilot.com/blog/pricing-page-best-practices/)

**Estimated Word Count**: 1,800 words

**Content Pillar**: Pricing Mastery

---

### 3. The Subscription Pricing Playbook: Lessons from 100 SaaS Companies

**Synopsis**
Patterns emerge when you study how successful SaaS companies price. This article synthesises pricing research into actionable principles, covering value metrics, tier structure, anchor pricing, and the psychology of subscription pricing.

**Lead Intro**
Every SaaS founder thinks their product is unique, and in many ways they're right. But when it comes to pricing, the differences matter less than the similarities. Studying how successful subscription businesses price reveals consistent patterns: how they choose value metrics, structure tiers, set anchor prices, and evolve pricing as they grow. These patterns aren't accidents. They emerge from the fundamental psychology of how customers perceive value and make purchasing decisions. Understanding them lets you skip the expensive experimentation phase and start with pricing that's at least directionally correct.

**Target Audience**
SaaS Founder

**Key Takeaway**
Your pricing will change, so optimise for learning over perfection; the company that iterates quickly on pricing beats the company that agonises over the initial decision.

**Salable Hook**
Demonstrates expertise in pricing evolution; positions Salable as enabling rapid iteration without billing rewrites

**Supporting Material**

- [OpenView: SaaS Pricing Models](https://openviewpartners.com/blog/saas-pricing-models/)
- [ChartMogul: SaaS Pricing Guide](https://chartmogul.com/resources/saas-pricing/)
- [ProfitWell: Pricing Page Teardowns](https://www.profitwell.com/recur/all/pricing-page-teardown)

**Estimated Word Count**: 2,500 words

**Content Pillar**: Pricing Mastery

---

### 4. When to Optimise with Hybrid Pricing

**Synopsis**
Hybrid pricing captures more value by combining models, but adds complexity customers need to navigate. This article explores when hybrid structures make sense, the trade-off between value capture and customer clarity, common patterns, and how to get it right.

**Lead Intro**
Most SaaS products deliver value in more than one way. A collaboration tool provides value through the platform itself, through the number of people using it, and through how much work flows through it. Pricing only one of those dimensions means leaving the others uncaptured. That's the case for hybrid pricing: combining a base fee with per-seat charges, or a subscription with usage metering, or any mix that reflects how your product actually creates value for customers.

**Target Audience**
SaaS Founder

**Key Takeaway**
Hybrid pricing works when each component maps to a distinct value dimension and customers can still predict their costs.

**Salable Hook**
Positions Salable's Line Items as infrastructure that makes hybrid pricing practical—compose plans from flat-rate, per-seat, metered, and one-off components through configuration, not code.

**Supporting Material**

- [Salable Products & Pricing Guide](https://beta.salable.app/docs/products-and-pricing)
- [Salable Metered Usage Guide](https://beta.salable.app/docs/metered-usage)
- [Growth Unhinged: 2025 State of SaaS Pricing](https://www.growthunhinged.com/p/2025-state-of-saas-pricing-changes)
- [Metronome: State of Usage-Based Pricing 2025](https://metronome.com/state-of-usage-based-pricing-2025)

**Estimated Word Count**: 1,800 words

**Content Pillar**: Pricing Mastery

---

### 5. Feature Flags and Entitlements: A Practical Guide

**Synopsis**
Most SaaS teams start with plan-based access checks (`if user.plan === 'pro'`) that become technical debt limiting pricing flexibility. This article explains why feature flags and entitlements solve different problems, when to use each, and how connecting entitlements to subscription state eliminates the overhead of keeping billing and access control in sync.

**Lead Intro**
Every SaaS application must answer two questions: "Is this feature ready for users?" and "Has this user paid for this feature?" Feature flags answer the first—they're operational tools for rollouts, experiments, and kill switches. Entitlements answer the second—they're commercial tools that connect feature access to subscription state. Using one tool for both creates problems that compound over time. When you scatter `if (user.plan === 'pro')` checks throughout your codebase, every pricing change becomes a code change. Moving a feature between tiers means a refactor. Grandfathering existing customers means special-case logic. Custom enterprise deals mean plan proliferation. There's a better way.

**Target Audience**
Engineering Lead

**Key Takeaway**
Stop checking plan names in code. Check entitlements instead. Use feature flags for operational decisions (is this ready?), entitlements for commercial decisions (has this user paid?). Connect entitlements to subscription state so pricing changes don't require code deployments.

**Salable Hook**
Promotes Salable's entitlements as the commercial access layer that connects directly to subscription state—when subscriptions change, entitlements update automatically, eliminating sync logic.

**Supporting Material**

- [Martin Fowler: Feature Toggles](https://martinfowler.com/articles/feature-toggles.html)
- [Salable Documentation: Entitlements](https://beta.salable.app/docs/understanding-entitlements)

**Estimated Word Count**: 2,200 words

**Content Pillar**: Pricing Mastery

---

### 6. What Stripe Won't Tell You About Subscription Billing

**Synopsis**
Stripe handles payments brilliantly but leaves substantial billing complexity for you to solve. This article identifies the gaps between Stripe's capabilities and real-world subscription management needs, from entitlements to team billing to usage reconciliation.

**Lead Intro**
Stripe's documentation makes subscription billing look solved. Create a product, attach a price, generate a checkout session, done. The code samples work. The webhooks fire. It feels like you've implemented billing. Then reality intrudes. A customer wants to add seats mid-cycle. Another needs to pause their subscription. A third upgraded but your app still shows free-tier features. These aren't edge cases; they're the core of subscription management. Stripe handles payment processing, but the logic that sits between your application and Stripe, the entitlement checks, the seat management, the subscription lifecycle, that's on you.

**Target Audience**
SaaS Founder

**Key Takeaway**
Stripe is payment infrastructure, not billing software; the gap between processing payments and managing subscriptions is larger than most founders realise.

**Salable Hook**
Directly positions Salable as the missing layer on top of Stripe; strongest conversion-focused article in series

**Supporting Material**

- [Stripe Billing Documentation](https://stripe.com/docs/billing)
- [Salable Core Concepts](https://beta.salable.app/docs/core-concepts)
- [ProfitWell: Billing Complexity](https://www.profitwell.com/recur/all/subscription-billing-guide)

**Estimated Word Count**: 2,200 words

**Content Pillar**: Pricing Mastery

---

### 7. Why Letting Customers Pay Less Makes More Money

**Synopsis**
Customers don't fit neatly into pricing tiers, and rigid bundling forces a binary choice: overpay for features they won't use, or cancel and look elsewhere. This article argues that tailored plans—assembled from granular entitlements to match actual usage—generate less revenue than a full tier upgrade but far more than a cancellation, optimising for lifetime value over invoice value.

**Lead Intro**
Customers don't fit into tiers. Every customer uses your product differently—different features, different team sizes, different workflows—and a handful of predefined pricing plans can only approximate that reality. The approximation works for most customers most of the time. When it doesn't, those customers face a binary choice: pay for things they don't need, or leave.

**Target Audience**
SaaS Founder, Product Manager

**Key Takeaway**
Rigid tiers optimise for simplicity at the point of sale; flexible, tailored plans optimise for the months and years that follow.

**Salable Hook**
Positions Salable's composable pricing (line items, plan modifications, quantity management) as the infrastructure enabling retention-focused flexibility

**Supporting Material**

- [Invesp: Customer Acquisition vs Retention Costs](https://www.invespcro.com/blog/customer-acquisition-retention/)
- [Recurly: Reduce Churn Guide](https://recurly.com/blog/reduce-churn/)
- [Vitally: SaaS Churn Benchmarks](https://www.vitally.io/post/saas-churn-benchmarks)
- [Salable Subscriptions & Billing](https://beta.salable.app/docs/subscriptions-and-billing)
- [Salable Products & Pricing](https://beta.salable.app/docs/products-and-pricing)

**Estimated Word Count**: 1,800 words

**Content Pillar**: Pricing Mastery

---

## Series Summary

These seven articles establish Salable's expertise in subscription pricing strategy:

| Article                       | Angle                | Position                                          |
| ----------------------------- | -------------------- | ------------------------------------------------- |
| Hidden Cost of Simple Pricing | Challenge convention | Simplicity isn't the goal; value alignment is     |
| Pricing Page Failures         | Diagnostic           | Features don't convert; outcomes do               |
| Subscription Pricing Playbook | Synthesis            | Patterns emerge from studying success             |
| When to Optimise with Hybrid  | Exploration          | Single models miss value; combinations capture it |
| Feature Flags & Entitlements  | Practical guide      | Operational vs commercial access control          |
| What Stripe Won't Tell You    | Reality check        | Payments and billing are different problems       |
| Letting Customers Pay Less    | Counterintuitive     | Lower prices can mean higher lifetime revenue     |

Each article takes a definitive position, provides supporting evidence, and connects back to how Salable addresses the identified problem. The series builds credibility through insight rather than product promotion.
