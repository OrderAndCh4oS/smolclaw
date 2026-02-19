# Beta Features: Product Announcement Articles

This document contains 9 articles announcing and explaining new capabilities in Salable Beta. Each article positions a feature as a solution to a common billing challenge while demonstrating Salable's technical depth.

**Content Pillar**: Product Updates

**Publishing Cadence**: Distributed across the 12-week calendar, primarily on Thursdays

---

## Articles

### 1. Introducing Tiered Pricing: Volume Discounts Made Simple

**Synopsis**
Tiered pricing lets you reward customers who buy more without the complexity of custom enterprise deals. This article introduces Salable's tiered pricing capabilities, explaining graduated versus volume tiers and when to use each approach.

**Lead Intro**
Every growing SaaS hits the same wall: your biggest customers want volume discounts, but your billing system only knows one price per unit. You end up with spreadsheets tracking custom deals, manual invoice adjustments, and a pricing page that lies to your best customers. Tiered pricing solves this by encoding volume discounts directly into your pricing model. Buy more, pay less per unit, automatically calculated and invoiced without human intervention.

**Target Audience**
SaaS Founder

**Key Takeaway**
Graduated tiers charge each bracket at its own rate while volume tiers apply the qualifying rate to all units; choose graduated for most use cases unless you want dramatic discount cliffs.

**Salable Hook**
Promotes Salable's tiered pricing configuration; positions as turnkey solution for volume discounts without custom code

**Supporting Material**

- [Salable Tiered Pricing Documentation](https://beta.salable.app/docs/core-concepts#tiered-pricing)
- [Stripe Volume and Graduated Pricing](https://stripe.com/docs/products-prices/pricing-models#tiered-pricing)
- [Price Intelligently: Volume Pricing Guide](https://www.priceintelligently.com/blog/saas-volume-pricing)

**Estimated Word Count**: 1,600 words

**Content Pillar**: Product Updates

---

### 2. Line Items: Build Any Pricing Model from Composable Parts

**Synopsis**
Line items are Salable's building blocks for flexible pricing. This article explains how combining flat-rate, per-seat, metered, and one-off charges in a single plan lets you create pricing models that match how customers actually use your product.

**Lead Intro**
Most billing systems force you to choose: flat monthly fee or usage-based pricing. Per-seat or metered. Base charge or add-ons. But real products rarely fit these neat categories. Your project management tool might have a monthly platform fee, charge per active user, and bill for storage overages, all in the same subscription. Line items make this natural. Instead of contorting your product to fit your billing system, you compose charges that reflect your actual value delivery.

**Target Audience**
Product Manager

**Key Takeaway**
Line items are composable pricing primitives: combine flat-rate for predictable revenue, per-seat for team scaling, metered for usage alignment, and one-off for setup fees, all in one plan.

**Salable Hook**
Promotes Salable's line items architecture; demonstrates unique flexibility vs competitors who force single pricing models

**Supporting Material**

- [Salable Line Items Guide](https://beta.salable.app/docs/line-items)
- [Salable Products and Pricing Overview](https://beta.salable.app/docs/products-and-pricing)
- [OpenView: The Hybrid Pricing Model](https://openviewpartners.com/blog/hybrid-pricing-model/)

**Estimated Word Count**: 2,000 words

**Content Pillar**: Product Updates

---

### 3. Multi-Currency Support: Sell Globally from Day One

**Synopsis**
Selling internationally shouldn't require rebuilding your pricing infrastructure. This article covers Salable's multi-currency support, from configuring prices per currency to automatic detection at checkout.

**Lead Intro**
Your first international customer just signed up, and they're asking why they have to pay in dollars. Currency conversion fees eat into their budget, and the psychological friction of foreign pricing makes your product feel less accessible. You could calculate exchange rates manually, but they fluctuate daily and your billing system doesn't know the difference between USD and EUR anyway. Multi-currency support removes this barrier. Configure prices in the currencies your customers use, and let the checkout flow present the right price automatically.

**Target Audience**
SaaS Founder

**Key Takeaway**
Set localised prices in each currency rather than relying on conversion; customers respond better to round local numbers than mathematically converted amounts.

**Salable Hook**
Promotes Salable's multi-currency support; positions as enabler for global expansion without billing infrastructure rebuild

**Supporting Material**

- [Salable Multi-Currency Documentation](https://beta.salable.app/docs/products-and-pricing#multi-currency)
- [Stripe Multi-Currency Overview](https://stripe.com/docs/currencies)
- [Paddle: Pricing Localisation Guide](https://www.paddle.com/resources/pricing-localization)

**Estimated Word Count**: 1,400 words

**Content Pillar**: Product Updates

---

### 4. Grantee Groups: Team Subscriptions Done Right

**Synopsis**
Managing team access within subscriptions creates complexity that simple per-seat billing doesn't address. This article introduces grantee groups, which model the relationship between billing owners, team members, and seat allocation.

**Lead Intro**
Per-seat pricing sounds simple until you implement it. Who pays and who uses aren't the same question. A company administrator buys 50 seats, but the individual team members need access. Adding someone to the subscription shouldn't require the billing owner to click buttons in your UI. And what happens when someone leaves the team? Grantee groups model these relationships explicitly. The owner holds the billing relationship, the grantees receive access, and the group manages membership. Changes propagate automatically, seat limits enforce themselves, and your code doesn't need to track who paid for whom.

**Target Audience**
Engineering Lead

**Key Takeaway**
Separate billing ownership from access grants; grantee groups let administrators manage team membership without touching subscription settings.

**Salable Hook**
Promotes Salable's grantee groups; positions as solution for enterprise team billing complexity that competitors handle poorly

**Supporting Material**

- [Salable Grantee Groups Guide](https://beta.salable.app/docs/grantee-groups)
- [Salable Entitlements Documentation](https://beta.salable.app/docs/understanding-entitlements)
- [SaaStr: Enterprise Seat Management](https://www.saastr.com/seat-based-pricing/)

**Estimated Word Count**: 1,800 words

**Content Pillar**: Product Updates

---

### 5. The Cart System: Core Products with Add-Ons Done Right

**Synopsis**
Modern SaaS products rarely exist in isolation—customers want a core product plus add-ons, plugins, and extensions. This article covers Salable's cart system, which bundles multiple plans into a single subscription and supports adding, removing, or replacing plans after purchase.

**Lead Intro**
Your customer wants your Professional plan plus the Analytics add-on, the API Access module, and maybe the White Label extension. Traditional billing systems force a choice: separate subscriptions that fragment the customer relationship, or a monolithic plan that bundles everything whether customers want it or not. Neither works. Salable's cart system solves this by letting customers purchase multiple plans as a single subscription. The core product and add-ons live together, billed together, managed together. And when needs change, customers can add new capabilities, remove what they don't use, or replace one add-on with another—all without creating subscription chaos.

**Target Audience**
Product Manager

**Key Takeaway**
Cart-based checkout creates composable subscriptions: bundle core products with add-ons at purchase, then let customers modify their bundle as needs evolve without managing multiple subscriptions.

**Salable Hook**
Promotes Salable's cart system; differentiates from competitors who only support single-plan subscriptions

**Supporting Material**

- [Salable Cart and Checkout Guide](https://beta.salable.app/docs/cart-and-checkout)
- [Stripe Checkout Sessions](https://stripe.com/docs/payments/checkout)
- [Baymard Institute: Cart Abandonment Stats](https://baymard.com/lists/cart-abandonment-rate)

**Estimated Word Count**: 1,500 words

**Content Pillar**: Product Updates

---

### 6. Webhooks: Real-Time Billing Events for Your Application

**Synopsis**
Polling for subscription changes is slow and unreliable. This article introduces Salable's webhook system, covering event types, delivery guarantees, and how to build responsive applications that react to billing events as they happen.

**Lead Intro**
Your customer just upgraded their plan, but your application still shows them the old features. Maybe your cron job will catch it in an hour. Maybe tomorrow. Polling for subscription changes works until it doesn't, and when it fails, customers notice. Webhooks flip the model. Instead of asking "has anything changed?" every few minutes, your application receives a notification the moment a change occurs. Subscription created, payment failed, usage recorded: your system knows immediately. The customer upgrades at 2:47 PM, and by 2:47 PM their new features are live.

**Target Audience**
Engineering Lead

**Key Takeaway**
Webhooks let your application respond to billing events in real-time; customers see changes instantly instead of waiting for your next sync cycle.

**Salable Hook**
Promotes Salable's webhook system; positions real-time sync as table stakes that Salable handles out of the box

**Supporting Material**

- [Salable Webhooks Documentation](https://beta.salable.app/docs/webhooks)
- [Stripe Webhook Best Practices](https://stripe.com/docs/webhooks/best-practices)
- [Svix: Webhook Security Guide](https://www.svix.com/blog/webhook-security/)

**Estimated Word Count**: 2,200 words

**Content Pillar**: Product Updates

---

### 7. Flexible Billing: Beyond Monthly Subscriptions

**Synopsis**
Not every product fits a monthly billing cycle. This article explores Salable's flexible billing intervals: daily, weekly, monthly, and annual options with custom interval multiples for quarterly, biannual, and other patterns.

**Lead Intro**
Monthly billing became the SaaS default because it was easy, not because it was optimal. Some customers want annual contracts for budget predictability. Others need weekly billing aligned with their pay cycles. High-velocity products might bill daily. Forcing everyone into monthly subscriptions leaves money on the table: annual prepay improves cash flow, while weekly billing reduces churn in price-sensitive segments. Flexible billing intervals let you meet customers where they are instead of where your billing system allows.

**Target Audience**
SaaS Founder

**Key Takeaway**
Annual billing typically increases customer lifetime value by 15-20% through reduced churn and improved cash flow; offer it as an option even if monthly remains your default.

**Salable Hook**
Promotes Salable's flexible billing intervals; positions as enabler for pricing experimentation without engineering work

**Supporting Material**

- [Salable Billing Intervals Guide](https://beta.salable.app/docs/products-and-pricing#billing-intervals)
- [ProfitWell: Annual vs Monthly Pricing](https://www.profitwell.com/recur/all/annual-vs-monthly-pricing)
- [Chargebee: Billing Cycle Strategies](https://www.chargebee.com/resources/glossary/billing-cycle/)

**Estimated Word Count**: 1,600 words

**Content Pillar**: Product Updates

---

### 8. Anonymous to Authenticated: Frictionless Checkout Flows

**Synopsis**
Requiring account creation before checkout kills conversions. This article explains Salable's anonymous checkout flow, which captures payment first and links the subscription to a user account after authentication.

**Lead Intro**
Your potential customer found your pricing page, selected a plan, and clicked "Subscribe." Then you asked them to create an account. Password requirements, email verification, maybe phone number for good measure. Half of them left. Anonymous checkout removes this friction. Customers complete payment with just an email address, receiving immediate access via a session token. When they create an account later, the subscription transfers automatically. The payment is captured when intent is highest, account creation happens when it's convenient.

**Target Audience**
Product Manager

**Key Takeaway**
Checkout conversion typically improves 10-15% when account creation moves after payment rather than before; capture revenue first, profiles second.

**Salable Hook**
Promotes Salable's anonymous checkout flow; positions as conversion optimisation built into the platform

**Supporting Material**

- [Salable Checkout Documentation](https://beta.salable.app/docs/cart-and-checkout#anonymous-checkout)
- [Baymard Institute: Account Creation UX](https://baymard.com/blog/checkout-guest-account-creation)
- [Stripe: Optimising Checkout Conversion](https://stripe.com/docs/payments/checkout/best-practices)

**Estimated Word Count**: 1,500 words

**Content Pillar**: Product Updates

---

### 9. Stripe Webhooks Without the Pain: How Salable Handles the Hard Parts

**Synopsis**
Stripe webhooks look simple in tutorials but become a reliability nightmare in production. This article reveals the hidden complexity of webhook handling—signature verification, retry logic, idempotency, event ordering—and explains how Salable's multi-stage processing pipeline handles it all automatically.

**Lead Intro**
The Stripe webhook documentation makes it look easy: receive an event, verify the signature, process the payload. Three steps. What the documentation doesn't mention is what happens when your server is down during a critical event. Or when the same event arrives twice. Or when a subscription update arrives before the subscription created event. Or when your database transaction fails mid-processing and Stripe retries the webhook while you're in an inconsistent state. Production webhook handling is a reliability engineering problem that most teams underestimate until they're debugging lost subscriptions at 2 AM. Salable's infrastructure handles these edge cases with a battle-tested pipeline that processes thousands of events daily without dropping a single one.

**Target Audience**
Engineering Lead

**Key Takeaway**
Stripe webhook reliability requires exponential backoff retries, idempotent processing, event ordering guarantees, and dead-letter queues for failed events; Salable handles all of this so you don't have to.

**Salable Hook**
Core infrastructure differentiator; positions Salable as solving the hardest part of Stripe integration that most developers underestimate

**Supporting Material**

- [Salable Webhooks Documentation](https://beta.salable.app/docs/webhooks)
- [Stripe Webhook Best Practices](https://stripe.com/docs/webhooks/best-practices)
- [AWS: Building Reliable Event-Driven Systems](https://aws.amazon.com/blogs/compute/building-resilient-serverless-patterns-by-combining-messaging-services/)
- [Svix: Why Webhooks Are Harder Than They Look](https://www.svix.com/blog/why-webhooks-are-harder-than-they-look/)

**Estimated Word Count**: 2,500 words

**Content Pillar**: Product Updates

---

## Series Summary

These nine articles cover the major capabilities that differentiate Salable Beta from legacy billing solutions:

| Feature                 | Business Value                        | Primary Audience |
| ----------------------- | ------------------------------------- | ---------------- |
| Tiered Pricing          | Automated volume discounts            | SaaS Founder     |
| Line Items              | Flexible pricing composition          | Product Manager  |
| Multi-Currency          | Global market access                  | SaaS Founder     |
| Grantee Groups          | Team subscription management          | Engineering Lead |
| Cart System             | Composable subscriptions with add-ons | Product Manager  |
| Webhooks                | Instant response to billing events    | Engineering Lead |
| Flexible Billing        | Interval customisation                | SaaS Founder     |
| Anonymous Checkout      | Conversion optimisation               | Product Manager  |
| Stripe Webhook Handling | Production-grade reliability          | Engineering Lead |

Each article includes working examples, implementation guidance, and links to detailed documentation for readers who want to start building immediately.
