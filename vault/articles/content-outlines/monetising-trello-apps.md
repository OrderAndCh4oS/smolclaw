# Monetising Trello Apps: Power-Up Revenue Series

This document contains 5 articles focused on monetising Trello Power-Ups. The series covers the marketplace landscape, pricing strategies, access control implementation, and migration from free to paid.

**Content Pillar**: Marketplace Monetisation

**Publishing Cadence**: Distributed across Weeks 5-9, primarily on Tuesdays

---

## Articles

### 1. The Trello Power-Up Monetisation Landscape: What You Need to Know

**Synopsis**
Trello's Power-Up ecosystem has evolved from a feature playground into a legitimate marketplace. This article maps the landscape: what's possible with paid Power-Ups, what Trello's policies allow, and where the revenue opportunities actually lie.

**Lead Intro**
Trello's Power-Up marketplace sits at an interesting inflection point. For years, most Power-Ups were free, built as marketing tools or side projects. But as Trello Enterprise grew and the ecosystem matured, paid Power-Ups became viable businesses. Some developers now generate substantial recurring revenue from tools that enhance project management, automate workflows, or integrate with external services. The opportunity is real, but navigating it requires understanding Trello's policies, user expectations, and the technical landscape of Power-Up billing.

**Target Audience**
Marketplace Developer

**Key Takeaway**
Trello users are increasingly willing to pay for Power-Ups that solve real problems, but pricing must respect the ecosystem's collaborative nature, where one purchaser often enables access for an entire board or workspace.

**Salable Hook**
Positions Salable as the billing platform for Trello Power-Ups; demonstrates marketplace expertise

**Supporting Material**

- [Trello Power-Up Documentation](https://developer.atlassian.com/cloud/trello/power-ups/)
- [Atlassian Marketplace Guidelines](https://developer.atlassian.com/platform/marketplace/listing-paid-cloud-apps/)

**Estimated Word Count**: 1,600 words

**Content Pillar**: Marketplace Monetisation

---

### 2. Per-Seat Pricing for Trello Power-Ups: The $5-15 Sweet Spot

**Synopsis**
Per-seat pricing works well for Trello Power-Ups because it aligns cost with team size. This article covers pricing benchmarks, the psychological dynamics of per-seat costs in collaborative tools, and implementation patterns.

**Lead Intro**
Pricing a Trello Power-Up feels like guessing in the dark. Charge too little and you leave revenue on the table. Charge too much and teams balk at adding another line item to their tooling budget. The data from successful Power-Ups points to a surprisingly consistent range: $5-15 per seat per month works for most use cases. This isn't arbitrary. It's the range where individual contributors can expense the cost without approval, while still generating meaningful revenue as teams scale.

**Target Audience**
Marketplace Developer

**Key Takeaway**
Price at the expense report threshold: $5-15/seat/month lets individual users adopt without procurement friction while generating real revenue as teams grow.

**Salable Hook**
Promotes Salable's per-seat pricing; positions as purpose-built for collaborative tool monetisation

**Supporting Material**

- [Salable Per-Seat Pricing Guide](https://beta.salable.app/docs/products-and-pricing)
- [Trello Pricing Page](https://trello.com/pricing) (for ecosystem context)
- [Price Intelligently: Per-User Pricing](https://www.priceintelligently.com/blog/per-user-pricing)

**Estimated Word Count**: 1,800 words

**Content Pillar**: Marketplace Monetisation

---

### 3. Implementing Workspace-Based Access for Your Trello Power-Up

**Synopsis**
Trello's workspace model creates natural boundaries for subscription access. This article covers implementing workspace-scoped subscriptions, handling board-level visibility, and managing the relationship between Trello's permissions and your billing.

**Lead Intro**
When a customer subscribes to your Power-Up, who gets access? The individual user? Everyone on the board? The entire workspace? Trello's permission model gives you flexibility, but that flexibility can become confusion if you don't design access control intentionally. Most successful paid Power-Ups scope access at the workspace level because it matches how teams think about tool budgets. The workspace administrator purchases, and everyone in the workspace benefits. Implementing this pattern requires understanding how Trello identifies workspaces and how to sync that identity with your subscription system.

**Target Audience**
Engineering Lead

**Key Takeaway**
Scope subscriptions to Trello workspaces, not boards or users; workspace billing matches how teams budget and reduces friction when boards are created or archived.

**Salable Hook**
Promotes Salable's grantee groups for workspace-scoped access; shows how Salable maps to Trello's identity model

**Supporting Material**

- [Trello REST API: Organisations](https://developer.atlassian.com/cloud/trello/rest/api-group-organizations/)
- [Salable Grantee Groups](https://beta.salable.app/docs/grantee-groups)
- [Trello Power-Up Client Library](https://developer.atlassian.com/cloud/trello/power-ups/client-library/)

**Estimated Word Count**: 2,000 words

**Content Pillar**: Marketplace Monetisation

---

### 4. Freemium vs. Free Trial: Conversion Strategies for Power-Ups

**Synopsis**
Both freemium and free trial models can work for Trello Power-Ups, but they suit different product types and user behaviours. This article compares the two approaches with data-driven recommendations for when each strategy wins.

**Lead Intro**
Your Power-Up needs a path from discovery to payment, but which path works better? Freemium keeps free users forever, betting that some percentage will upgrade for premium features. Free trials give full access temporarily, betting that users who experience the full product will pay to keep it. Neither strategy is universally better. The right choice depends on how quickly users discover your Power-Up's value, how sticky the free version is, and whether premium features are nice-to-have or necessary for serious use.

**Target Audience**
Marketplace Developer

**Key Takeaway**
Choose freemium when your Power-Up delivers value immediately but advanced users need more; choose trials when the core value requires features that free tiers can't demonstrate.

**Salable Hook**
Promotes Salable's trial and entitlement configuration; positions as enabling conversion experimentation

**Supporting Material**

- [Salable Trial Configuration](https://beta.salable.app/docs/products-and-pricing#trials)
- [OpenView: Freemium vs Free Trial](https://openviewpartners.com/blog/freemium-vs-free-trial/)
- [Lenny's Newsletter: Conversion Benchmarks](https://www.lennysnewsletter.com/p/conversion-rate-benchmarks)

**Estimated Word Count**: 1,600 words

**Content Pillar**: Marketplace Monetisation

---

### 5. From Free to Paid: A Step-by-Step Trello Power-Up Migration

**Synopsis**
Introducing pricing to an existing free Power-Up risks alienating users who never expected to pay. This guide provides a step-by-step migration plan: communicating changes, grandfathering existing users, and implementing billing without disrupting active workspaces.

**Lead Intro**
You built a Power-Up, gave it away for free, and now thousands of teams depend on it. Introducing pricing feels like betrayal. But running infrastructure costs money, and your time has value too. The alternative to paid pricing isn't sustainable. The good news: free-to-paid transitions don't have to be disasters. Thoughtful communication, generous grandfathering, and careful implementation can convert free users to paying customers while maintaining goodwill. Some of your most loyal free users become your strongest paid advocates when they understand the value exchange.

**Target Audience**
Marketplace Developer

**Key Takeaway**
Grandfather existing active users generously, at least six months free and permanent discounts; the goodwill value exceeds the revenue you'd capture from forced conversions.

**Salable Hook**
Positions Salable as partner for monetisation transitions; demonstrates expertise in sensitive pricing migrations

**Supporting Material**

- [Baremetrics: Free to Paid Migration](https://baremetrics.com/blog/going-from-free-to-paid)
- [Superhuman: Pricing Migration Case Study](https://canny.io/blog/superhuman-pricing-strategy/)

**Estimated Word Count**: 2,200 words

**Content Pillar**: Marketplace Monetisation

---

## Series Summary

This five-article series covers the complete journey from understanding the Trello monetisation opportunity to executing a successful paid Power-Up strategy:

| Article                | Focus                | Outcome                        |
| ---------------------- | -------------------- | ------------------------------ |
| Monetisation Landscape | Market Understanding | Know where opportunities exist |
| Per-Seat Pricing       | Pricing Strategy     | Set sustainable price points   |
| Workspace Access       | Implementation       | Build correct access control   |
| Freemium vs. Trial     | Conversion Strategy  | Choose the right growth model  |
| Free to Paid Migration | Execution            | Transition without user revolt |

The series targets developers who have built or are building Trello Power-Ups and want to turn them into sustainable businesses. Each article provides actionable guidance backed by ecosystem-specific context.
