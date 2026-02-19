---
title: 'Per-Seat Pricing for Enterprise Miro Apps'
description: "Large organisations don't buy tools the way individuals do. Per-seat pricing speaks their language and captures value as your plugin becomes embedded in how larger teams work."
publishedAt: 2026-05-01
category: Monetising Miro Apps
author: sean-cooper
tags:
    - miro
    - pricing
    - enterprise
    - per-seat
draft: false
featured: false
---

Flat-rate pricing works until an enterprise procurement team asks for a quote. Large organisations don't buy tools the way individuals do. They need to allocate costs to departments, manage licenses centrally, and forecast spending as teams grow. Per-seat pricing speaks their language. When you charge per user, enterprises can model your plugin's cost alongside every other tool in their stack. More importantly, per-seat pricing captures value as your plugin becomes embedded in how larger teams work. A plugin that's essential to fifty people should generate more revenue than one used by five, and with per-seat pricing, it does.

Moving to per-seat pricing isn't just changing a number in your billing configuration. It requires rethinking how you identify users, manage access, and communicate with customers who expect the processes that come with enterprise software. The technical implementation matters, but so does the positioning and the operational infrastructure that makes per-seat licensing feel professional rather than improvised.

## When Per-Seat Pricing Makes Sense

Per-seat pricing works when your plugin's value scales with the number of people using it. If each additional user extracts meaningful value from your plugin, charging per seat aligns your revenue with the utility you provide. If usage concentrates in a handful of power users regardless of team size, per-seat pricing creates friction without capturing proportionally more value.

Enterprise buyers expect per-seat pricing because it matches their mental model for software costs. Their finance teams build spreadsheets that calculate per-employee costs for every tool in the stack. When your plugin charges flat-rate regardless of team size, it doesn't fit neatly into these models. Procurement asks questions like "what's the per-user cost?" and flat-rate answers create confusion.

The scalability of per-seat pricing also matters for your business economics. A plugin that captures five large enterprise customers at flat rates might generate less revenue than one that captures twenty mid-market companies paying per seat. As your customers grow, their payments grow with them, creating natural revenue expansion without needing to sell new accounts.

Consider whether your target customers are large enough to have procurement processes. Companies with fewer than fifty employees often buy software like consumers: someone finds a tool, puts it on a credit card, and expenses it. Companies with hundreds or thousands of employees have formal procurement, vendor management, and IT approval processes. Per-seat pricing signals that you're prepared to work within those processes.

## Setting Per-Seat Prices

Per-seat pricing for Miro plugins typically ranges from five to twenty dollars per seat per month, though specialised enterprise tools can command more. The right price depends on the value each user extracts, the competitive landscape, and the total cost your target customers will tolerate.

Calculate backwards from what large customers will pay. If you're targeting enterprises with two hundred Miro users, and they'd reasonably budget five thousand dollars annually for a plugin like yours, your per-seat price should be around two dollars per month. If they'd budget fifty thousand, you can charge closer to twenty dollars per seat. Understanding total contract values matters more than optimising the per-seat number in isolation.

Volume discounts are expected in enterprise sales and should be built into your pricing from the start. A company buying five hundred seats expects to pay less per seat than one buying fifty. Structure discounts that reward commitment without eroding margin excessively. Tiers at fifty, one hundred, two hundred fifty, and five hundred seats are common breakpoints, with discounts typically ranging from ten to forty percent off list price for the highest volumes.

Annual billing provides another discount lever. Offering two months free for annual commitment (effectively sixteen percent off) is standard practice. Annual contracts improve your cash flow, reduce churn by creating switching costs, and give large customers the predictability they want for budget planning.

## Managing Seats and Access

Per-seat pricing requires knowing who your seats are. In Miro's context, this means connecting Miro user identities to subscription entitlements and tracking which users have been granted access by paying customers.

The simplest approach uses Miro's team structure. When an organisation subscribes, you grant access to members of their Miro team. Adding someone to the team grants plugin access; removing them revokes it. This approach works but may not match how customers want to manage licenses if their Miro team structure doesn't align with who should have plugin access.

More sophisticated implementations separate seat management from Miro's native identity. Customers get an admin interface where they can assign seats to specific users, invite users who aren't yet on their Miro team, and track who's using their allocation. This approach requires more development but gives enterprises the control they expect.

Grantee groups provide a pattern for managing seat assignments independent of Miro's team structure. A grantee group represents a pool of seats that administrators can allocate to specific users. When someone checks whether they have access to your plugin, you verify whether they're a member of a grantee group with active entitlements. Platforms like Salable provide grantee group functionality that handles the complexity of seat assignment, making it possible to offer enterprise-grade seat management without building it from scratch.

Decide what happens when customers exceed their seat allocation. Some plugins hard-cap access: once all seats are assigned, additional users can't access the plugin until someone is removed or more seats are purchased. Others allow overage with additional charges, which reduces friction but requires billing infrastructure that can handle variable usage. Still others allow temporary overage with notifications, trusting that customers will true-up their seat counts periodically.

## Building Admin Controls Enterprises Expect

Enterprise customers don't just buy seats; they expect to manage those seats. Building an administrative interface transforms your plugin from a tool into something that feels like enterprise software.

The admin dashboard should show seat utilisation: how many seats are purchased, how many are assigned, and who holds them. Administrators need to add and remove users without involving your support team. They need to see usage data, at least at the level of who's actually using the seats assigned to them, to justify renewals and identify unused licenses.

User provisioning integrates with enterprise identity systems through SCIM (System for Cross-domain Identity Management) or similar protocols. When companies use Okta, Azure AD, or other identity providers, they expect software licenses to provision automatically as part of their employee onboarding process. Supporting SCIM moves your plugin from "yet another thing IT has to manage manually" to something that fits into existing workflows.

Role-based access within your admin interface matters for larger organisations. The person who manages billing might not be the person who assigns seats, and neither might be the users who actually use the plugin. Allowing customers to grant different levels of access to different administrators reduces the chance of accidental changes and satisfies security teams that worry about who controls what.

Audit logs track what administrators did and when. When an enterprise security team asks who had access to your plugin on a specific date, or when billing disputes arise about seat counts, audit logs provide the authoritative record. Building this logging from the start is far easier than retrofitting it when customers demand it.

## The Sales Process for Per-Seat Enterprise

Selling per-seat licenses to enterprises differs from self-service signups. The sales cycle is longer, involves more stakeholders, and requires different content and touchpoints.

Enterprise buyers want to talk to someone before committing. A "contact sales" option for large deployments signals that you're ready for enterprise conversations. The initial call qualifies the opportunity: how many seats they need, what their timeline looks like, who the decision-makers are, and what their evaluation criteria include. This information shapes how you engage through the rest of the sales process.

Security questionnaires and vendor assessments are standard for enterprise procurement. Prepare documentation about your security practices, data handling, and compliance certifications before you need them. Having SOC 2 compliance or even just thorough security documentation accelerates deals; lacking it can stall or kill them.

Pilot programmes give enterprises confidence before committing to large deployments. Offering a time-limited trial for a subset of users lets them evaluate your plugin's fit with their workflows without the risk of a full commitment. Structure pilots with clear success criteria so everyone knows what constitutes a successful evaluation.

Contracts for enterprise deals rarely use your standard terms of service. Expect redlines, custom clauses, and negotiations that take longer than you'd like. Having a legal review of your standard enterprise agreement before you start selling saves time later. Some terms are worth holding firm on; others are concessions that cost you nothing but make customers feel heard.

## Operational Infrastructure for Per-Seat Billing

Managing per-seat subscriptions requires billing infrastructure that handles complexity gracefully. Customers add and remove seats mid-cycle. They upgrade and downgrade. They dispute charges and request credits. Each scenario needs a defined process and ideally automated handling.

Proration ensures customers pay fairly when their seat count changes. Adding ten seats midway through a billing cycle should charge for half a month, not a full month. Removing seats should credit unused time toward future invoices. The math isn't complex, but implementing it correctly in billing systems requires attention to edge cases.

Annual contracts with monthly seat adjustments combine predictability with flexibility. Customers commit to a minimum seat count annually, getting the associated discount, while having the ability to add seats as needed. Tracking the distinction between committed seats (which get the discount) and additional seats (which may not) adds billing complexity but meets how enterprises want to buy.

Handling billing for per-seat subscriptions manually is feasible for a handful of enterprise customers but doesn't scale. Platforms like Salable provide per-seat billing capabilities with automatic proration, grantee group management, and the administrative interfaces that enterprises expect. Using purpose-built infrastructure rather than building it yourself lets you focus on your plugin's value proposition while offering billing experiences that match larger competitors.

The jump from flat-rate to per-seat pricing represents more than a pricing model change. It's a commitment to serving enterprise customers and building the operational infrastructure they require. Done well, per-seat pricing unlocks a customer segment with larger budgets, longer retention, and growth potential that compounds as their organisations expand. Done poorly, it creates billing confusion, access management headaches, and support burden that overwhelms small teams. Understanding what enterprise customers expect and building to meet those expectations positions your Miro plugin for sustainable growth in the most lucrative segment of the market.
