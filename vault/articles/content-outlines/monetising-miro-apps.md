# Monetising Miro Apps: Plugin Revenue Series

This document contains 6 articles focused on monetising Miro plugins and applications. The series covers the Miro marketplace, pricing strategies, access control, and building sustainable plugin businesses.

**Content Pillar**: Marketplace Monetisation

**Publishing Cadence**: Distributed across Weeks 5-10, primarily on Thursdays

---

## Articles

### 1. The Miro Plugin Economy: Opportunities and Pricing Patterns

**Synopsis**
Miro's marketplace has grown rapidly as remote collaboration became standard. This article examines the current state of Miro plugin monetisation, identifying successful pricing patterns and underserved market segments.

**Lead Intro**
Miro transformed from a whiteboarding tool into a visual collaboration platform used by millions. That transformation created an ecosystem where plugins extend Miro's capabilities, from diagramming tools to workshop facilitation to data visualisation. Unlike more mature marketplaces, Miro's plugin economy is still finding its shape. Pricing norms haven't calcified, and significant gaps remain where new plugins could capture substantial value. Understanding where the opportunities lie, and what successful plugins charge, positions you to build something sustainable rather than another free tool that drains your time.

**Target Audience**
Marketplace Developer

**Key Takeaway**
Miro's plugin marketplace rewards specialisation: plugins that solve narrow problems deeply outperform generic tools competing with Miro's native features.

**Salable Hook**
Positions Salable as the billing platform for Miro plugins; demonstrates marketplace expertise

**Supporting Material**

- [Miro Developer Platform](https://developers.miro.com/)
- [Miro Marketplace](https://miro.com/marketplace/)
- [Salable Core Concepts](https://beta.salable.app/docs/core-concepts)

**Estimated Word Count**: 1,600 words

**Content Pillar**: Marketplace Monetisation

---

### 2. Flat-Rate Pricing for Miro Plugins: The $0-30 Decision

**Synopsis**
Flat-rate monthly pricing keeps Miro plugin billing simple, but setting the right price requires understanding both the value delivered and the competitive landscape. This article provides a framework for finding your flat-rate sweet spot.

**Lead Intro**
Per-seat pricing works for some Miro plugins, but many find flat-rate simpler, both to implement and to explain. A team of five pays the same as a team of fifty, which feels unfair until you realise that larger teams rarely use plugins proportionally more. The question becomes: what monthly rate captures enough value to sustain development without pricing out smaller teams? Most successful flat-rate Miro plugins land between $10 and $30 per month, but the right number depends on your plugin's value concentration and your target customer size.

**Target Audience**
Marketplace Developer

**Key Takeaway**
Set flat-rate pricing based on the value to your typical customer, not your best customer; a $15/month plugin that sells widely beats a $50/month plugin that only enterprises consider.

**Salable Hook**
Promotes Salable's flat-rate pricing configuration; positions as simple setup for SMB-focused plugins

**Supporting Material**

- [Salable Flat-Rate Pricing](https://beta.salable.app/docs/products-and-pricing)
- [Miro Marketplace Pricing Examples](https://miro.com/marketplace/)
- [ProfitWell: Value Metric Selection](https://www.profitwell.com/recur/all/pricing-value-metric)

**Estimated Word Count**: 1,600 words

**Content Pillar**: Marketplace Monetisation

---

### 3. Per-Seat Pricing for Enterprise Miro Apps

**Synopsis**
Enterprise customers expect per-seat pricing because it aligns with how they budget and manage software. This article covers implementing per-seat models for Miro apps targeting larger organisations, including seat management, admin controls, and pricing strategies that scale with team size.

**Lead Intro**
Flat-rate pricing works until an enterprise procurement team asks for a quote. Large organisations don't buy tools the way individuals do. They need to allocate costs to departments, manage licenses centrally, and forecast spending as teams grow. Per-seat pricing speaks their language. When you charge per user, enterprises can model your plugin's cost alongside every other tool in their stack. More importantly, per-seat pricing captures value as your plugin becomes embedded in how larger teams work. A plugin that's essential to fifty people should generate more revenue than one used by five—and with per-seat pricing, it does.

**Target Audience**
Marketplace Developer

**Key Takeaway**
Per-seat pricing unlocks enterprise sales by matching how large organisations budget, procure, and scale software; it's not just a pricing model, it's a go-to-market strategy.

**Salable Hook**
Promotes Salable's per-seat pricing and grantee groups; positions as enterprise-ready billing for Miro plugins

**Supporting Material**

- [Salable Per-Seat Pricing Guide](https://beta.salable.app/docs/products-and-pricing)
- [Salable Grantee Groups for Team Management](https://beta.salable.app/docs/grantee-groups)
- [Miro Enterprise Features](https://miro.com/enterprise/)
- [OpenView: Enterprise SaaS Pricing](https://openviewpartners.com/blog/enterprise-saas-pricing/)

**Estimated Word Count**: 2,000 words

**Content Pillar**: Marketplace Monetisation

---

### 4. Implementing Board-Based Access Control in Miro

**Synopsis**
Miro's data model centres on boards, which creates access control patterns distinct from other platforms. This article covers implementing subscription checks at the board level, handling permissions, and syncing Miro identities with your billing system.

**Lead Intro**
Miro users live in boards. They create boards, share boards, and collaborate on boards. Your plugin's access control should probably follow this pattern, granting access at the board level rather than forcing individual user subscriptions. But board-based access raises questions that user-based billing doesn't: who pays for a shared board? What happens when a board is duplicated? How do you handle boards that move between teams? Implementing board-scoped subscriptions requires understanding Miro's identity model and designing access checks that feel natural to how people actually use Miro.

**Target Audience**
Engineering Lead

**Key Takeaway**
Implement board-level access checks using the board owner's subscription status; this matches Miro's mental model and reduces licensing friction for collaborative teams.

**Salable Hook**
Promotes Salable's entitlements for board-scoped access; shows how Salable maps to Miro's identity model

**Supporting Material**

- [Miro REST API: Boards](https://developers.miro.com/reference/get-boards)
- [Miro Web SDK](https://developers.miro.com/docs/web-sdk-reference)
- [Salable Entitlements Guide](https://beta.salable.app/docs/understanding-entitlements)

**Estimated Word Count**: 2,000 words

**Content Pillar**: Marketplace Monetisation

---

### 5. Usage-Based Pricing for Miro Plugins: When Metering Makes Sense

**Synopsis**
Some Miro plugins deliver value that scales with usage rather than access. This article examines when usage-based pricing outperforms flat-rate or per-seat models, and how to implement metering for Miro-specific actions.

**Lead Intro**
Your Miro plugin processes data: maybe it generates diagrams from spreadsheets, exports boards to external tools, or analyses content for insights. Each operation has a cost to you, and the value delivered scales with volume. Flat-rate pricing would either undersell to power users or overprice for occasional use. Usage-based billing aligns your revenue with the value you create, charging more when customers get more. The challenge is identifying the right metric to meter and implementing tracking that feels fair rather than nickel-and-diming.

**Target Audience**
Marketplace Developer

**Key Takeaway**
Meter actions that correlate with value delivered and have meaningful marginal costs; exports, generations, and API calls are natural candidates, while passive features like viewing rarely warrant metering.

**Salable Hook**
Promotes Salable's metered usage billing; positions as enabling sophisticated pricing without infrastructure complexity

**Supporting Material**

- [Salable Metered Usage Guide](https://beta.salable.app/docs/metered-usage)
- [OpenView: Usage-Based Pricing Guide](https://openviewpartners.com/blog/usage-based-pricing/)
- [Kyle Poyar: Usage Pricing Metrics](https://kylepoyar.substack.com/)

**Estimated Word Count**: 1,800 words

**Content Pillar**: Marketplace Monetisation

---

### 6. Building a Miro Plugin Business: Beyond the First Dollar

**Synopsis**
Getting a Miro plugin to generate revenue is step one. This article covers the operational aspects of running a plugin business: support, iteration, marketing within the ecosystem, and scaling without burning out.

**Lead Intro**
Your plugin is earning money. Congratulations, you've crossed the hardest threshold in the marketplace. But what comes next? Customers expect support. Bugs need fixing. Miro releases new features that break your integration. Marketing doesn't stop once you have paying users; you need them to keep coming. The difference between a plugin that generates pocket money and one that becomes a real business lies in operational sustainability. Building systems that scale support, streamline development, and create growth loops lets you capture opportunity without sacrificing your sanity.

**Target Audience**
Marketplace Developer

**Key Takeaway**
Invest in support automation and documentation before you're overwhelmed; the cost of building these systems while small is far lower than trying to retrofit them during a support crisis.

**Salable Hook**
Positions Salable as reducing operational burden; billing handled so developers can focus on product and support

**Supporting Material**

- [Miro Developer Community](https://community.miro.com/)
- [Intercom: Support Scaling Guide](https://www.intercom.com/blog/scale-customer-support/)
- [Indie Hackers: Solo Business Operations](https://www.indiehackers.com/start)

**Estimated Word Count**: 2,200 words

**Content Pillar**: Marketplace Monetisation

---

## Series Summary

This six-article series guides developers from understanding the Miro opportunity through building a sustainable plugin business:

| Article             | Focus                 | Outcome                        |
| ------------------- | --------------------- | ------------------------------ |
| Plugin Economy      | Market Analysis       | Identify opportunities         |
| Flat-Rate Pricing   | Pricing Strategy      | Set sustainable prices for SMB |
| Per-Seat Enterprise | Enterprise Strategy   | Unlock larger customers        |
| Board-Based Access  | Implementation        | Build correct access control   |
| Usage-Based Pricing | Advanced Monetisation | Align revenue with value       |
| Building a Business | Operations            | Scale sustainably              |

The series serves developers at different stages: those researching the opportunity, those targeting enterprise customers, those implementing billing, and those scaling existing plugins into sustainable businesses. Each article combines strategic guidance with Miro-specific technical detail.
