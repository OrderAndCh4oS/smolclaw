---
title: 'Line Items: Build Any Pricing Model from Composable Parts'
description: 'Most billing systems force you to choose one pricing model. Line items let you combine flat-rate, per-seat, metered, and one-off charges into plans that reflect how customers actually use your product.'
publishedAt: 2026-01-27
category: Beta Features
author: sean-cooper
tags:
    - pricing
    - line-items
    - features
    - billing
draft: false
featured: false
---

# Line Items: Build Any Pricing Model from Composable Parts

<!-- IMAGE: Visual diagram showing different line item types combining into a single plan
     Placement: hero
     Suggested: Illustration of flat-rate, per-seat, metered, and one-off components merging -->

Most billing systems force you to choose: flat monthly fee or usage-based pricing. Per-seat or metered. Base charge or add-ons. But real products rarely fit these neat categories. Your project management tool might have a monthly platform fee, charge per active user, and bill for storage overages, all in the same subscription. Line items make this natural. Instead of contorting your product to fit your billing system, you compose charges that reflect your actual value delivery.

The limitations of single-model pricing become obvious the moment your product evolves. You launched with a simple per-user fee, but now enterprise customers want a predictable base cost. You added API access, but some customers hammer your endpoints while others barely touch them. Your professional services team offers implementation packages, and billing those separately fragments the customer relationship. Every pricing decision becomes a compromise between what makes business sense and what your billing system can actually do.

Line items dissolve this tension. Instead of picking one pricing model and shoehorning everything into it, you build plans from composable parts. Each part handles one dimension of value: a flat rate for platform access, per-seat charges for team growth, metered billing for variable usage, one-off fees for setup or implementation. Combined, they create pricing that mirrors how customers actually use and value your product.

## The Four Building Blocks

Salable provides four line item types, each designed for a specific kind of charge. Understanding when to use each one lets you construct pricing models that feel intuitive to customers while capturing value accurately.

<!-- IMAGE: Four cards showing each line item type with brief descriptions
     Placement: inline
     Suggested: Visual overview of flat-rate, per-seat, metered, and one-off line items -->

**Flat-rate line items** charge a fixed amount per billing period regardless of usage. They're the foundation of predictable revenue and work well for platform access, minimum commitments, or bundled features. A \$99/month base fee is a flat-rate line item. So is a \$200/month commitment that includes a certain usage threshold before metered charges kick in.

The stability of flat-rate charges benefits both sides of the transaction. Customers know exactly what they'll pay each month, which simplifies budgeting and reduces billing surprise. You get predictable recurring revenue that doesn't fluctuate with usage patterns. For products where the core value doesn't scale linearly with usage, flat-rate is often the right foundation.

**Per-seat line items** charge based on the number of users, seats, or licenses. The quantity can be fixed at purchase time or dynamic based on active usage. Per-seat pricing aligns revenue with team growth, which makes it popular for collaboration tools, productivity software, and anything where value multiplies as more people use it.

The key decision with per-seat pricing is whether seats are committed or active. Committed seats mean the customer pays for a fixed number whether they use them all or not, providing revenue predictability at the cost of potential customer friction when seats go unused. Active seats mean the customer pays only for seats in use during the billing period, which feels fairer to customers but creates revenue variability and potential gaming.

**Metered line items** charge based on measured consumption, calculated and invoiced at the end of each billing period. API calls, data transfer, storage, compute time, and transactions are classic metered charges. Metered billing captures value from high-usage customers who would otherwise be subsidised by low-usage customers on flat plans.

Metered pricing requires infrastructure to track usage accurately and report it before invoicing. The billing system needs to know that Customer A made 47,293 API calls last month while Customer B made 2,341. This tracking complexity is the cost of usage alignment, but for products with variable consumption patterns, it's often worth it.

**One-off line items** charge a single amount that doesn't recur. Setup fees, implementation packages, training sessions, and initial configuration belong here. They're purchased once, invoiced once, and don't appear on future bills.

One-off charges let you monetise work that happens outside the normal subscription relationship without creating separate invoicing streams. The customer sees one bill that includes their subscription and any one-time charges, keeping the relationship consolidated even when the charges have different characteristics.

## Combining Line Items into Plans

The real power of line items emerges when you combine them. A single plan can include multiple line items of different types, creating pricing models that would be impossible with single-model systems.

Consider a hypothetical analytics platform. The core platform provides dashboards and basic reporting, worth a predictable monthly fee. Team members need access, and each additional analyst increases the value the company extracts. Heavy users query the data warehouse extensively, and those queries cost real infrastructure. New customers need onboarding to get value quickly.

<!-- IMAGE: Plan configuration showing multiple line items with different pricing types
     Placement: inline
     Suggested: Screenshot of a plan with flat-rate, per-seat, and metered components -->

With line items, this translates naturally. The plan includes a \$199/month flat-rate for platform access, \$29/month per analyst seat, \$0.02 per data warehouse query, and a one-time \$500 onboarding fee. A small team with three analysts running moderate queries might pay \$286/month after the initial setup. An enterprise with 50 analysts running millions of queries pays proportionally more, reflecting the greater value they extract.

This composition works because each line item handles its own dimension independently. The flat-rate component is unaffected by seat count. The per-seat charge is unaffected by query volume. Metered billing is unaffected by team size. Each component does one thing well, and combining them creates sophisticated pricing without sophisticated configuration.

## Pricing Model Patterns

Certain combinations of line items appear repeatedly across successful SaaS businesses. Recognising these patterns helps you design pricing that fits your product's value delivery.

**Base plus usage** combines a flat-rate foundation with metered charges for consumption above a threshold. The base fee provides revenue predictability and includes some level of usage, while metered charges capture value from heavy users. This pattern works well when customers have widely varying usage but everyone needs a minimum level of service.

**Platform plus seats** pairs flat-rate platform access with per-seat growth. The platform fee covers infrastructure and capabilities that don't scale with users, while per-seat charges align revenue with the expanding value as more team members adopt the product. Collaboration and productivity tools often follow this pattern.

**Committed seats with overage** sets a minimum seat commitment with metered charges for seats beyond the commitment. The customer commits to paying for 10 seats monthly but can burst to 15 during busy periods with overage charges. This balances revenue predictability with customer flexibility.

**Tiered base with flat add-ons** offers multiple plan levels with different flat-rate bases, then adds capabilities through additional flat-rate line items. The customer picks their tier (Starter, Professional, Enterprise) and optionally adds modules (Analytics, API Access, White Label). Each piece has simple, predictable pricing while the combination creates significant variety.

**Usage-only with minimum** charges purely on consumption but enforces a minimum monthly spend. If actual usage falls below the minimum, the customer pays the minimum. If usage exceeds it, they pay actual usage. This protects your revenue floor while rewarding high-usage customers with pure consumption pricing.

## Designing for Customer Psychology

Pricing isn't just mathematics; it's communication. How you structure line items affects how customers perceive value and make purchasing decisions. A few principles from pricing psychology apply directly to line item design.

**Anchor high, discount down.** When combining line items, customers perceive value based on the total price before any bundled discounts. Showing the individual line item prices and then applying a bundle discount makes the value feel greater than showing the bundled price alone.

**Predictability reduces anxiety.** Customers prefer knowing what they'll pay. If your pricing includes metered components, consider including a usage threshold in the flat-rate portion so customers have a predictable baseline. The metered charges then feel like an option they control rather than an unpredictable cost.

**Simplicity wins at checkout.** While line items let you build complex pricing, the checkout experience should feel simple. Show the total monthly cost prominently, with line item breakdown available for customers who want it. Don't force everyone to parse the composition before buying.

**Separate value from cost.** One-off charges like setup fees can create friction if they feel like arbitrary costs. Frame them as value delivery: "Onboarding package includes dedicated setup session, data migration, and team training." The line item is still a one-off charge, but the messaging emphasises what the customer receives.

## Implementation Considerations

Building line-item-based plans requires coordination between your billing system, your application, and your customer-facing interfaces. Each component has a role to play.

Your billing system needs to understand line item composition natively. Salable handles this by letting you add multiple line items to a single plan, each with its own pricing type, currency, and configuration. The system calculates the combined invoice correctly, handling the interactions between flat, per-seat, metered, and one-off charges.

Your application needs to report usage for metered line items and track seat counts for per-seat charges. This means instrumenting the relevant actions (API calls, storage consumption, active users) and reporting them to the billing system before invoice generation. The accuracy of your billing depends on the accuracy of this reporting.

<!-- IMAGE: Architecture diagram showing usage tracking flowing to billing system
     Placement: diagram
     Suggested: Flowchart of application events becoming metered billing data -->

Your checkout flow needs to communicate the pricing clearly. For plans with multiple line items, show customers what they're getting and what each component costs. If quantities are configurable at checkout (like seat count), update the total dynamically as they adjust. If metered charges apply, explain how usage will be tracked and billed.

Your customer portal needs to show line item breakdown on invoices and subscription details. Customers should be able to see exactly what they're paying for and why. This transparency builds trust and reduces billing-related support requests.

## Evolving Your Pricing Over Time

One advantage of line-item-based pricing is adaptability. As your product evolves, you can add new line items without restructuring everything. Launch a new feature? Add it as an optional line item on existing plans or create a new add-on plan. Discover that a flat-rate component should scale with usage? Convert it to a metered line item.

This flexibility supports pricing experimentation. You can A/B test different line item combinations to see what resonates with customers. You can offer promotional line items that expire after a trial period. You can create customer-specific line items for enterprise deals without building entirely custom plans.

The key is treating line items as modular components that can be mixed, matched, and modified over time. Your initial pricing model doesn't have to be perfect because you have the tools to evolve it as you learn what customers value and what they'll pay for.

## The Shift in Thinking

Moving from single-model pricing to line-item composition requires a mental shift. Instead of asking "which pricing model should we use?" you ask "what are the different dimensions of value we deliver, and how should each be priced?"

Some dimensions are best served by flat charges: predictable, simple, easy to understand. Others align naturally with seat counts: value that scales with team size. Others depend on consumption: value that varies with usage. And some are one-time: value delivered once at the start of the relationship.

Once you see your product through this lens, pricing becomes less about constraints and more about expression. Line items let you say exactly what each component is worth and charge accordingly. The billing system handles the composition, calculation, and invoicing. You focus on delivering value; the pricing follows naturally.

The project management tool with platform fees, per-user charges, and storage billing isn't a complicated edge case anymore. It's just three line items doing what each does best, combined into a plan that reflects reality. And when reality changes, your plan can change with it.
