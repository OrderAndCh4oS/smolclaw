---
title: "Team Subscriptions: When One Seat Isn't Enough"
description: 'Your first customers were individuals. But now a company wants seats for their whole team, and simple questions get complicated. Who receives the invoice? How do team members get access?'
publishedAt: 2026-03-20
category: SaaS Startup Guides
author: sean-cooper
tags:
    - teams
    - subscriptions
    - billing
    - saas
draft: false
featured: false
---

# Team Subscriptions: When One Seat Isn't Enough

Your first customers were individuals, and per-user billing was straightforward. But now a company wants to buy seats for their whole team, and suddenly simple questions get complicated. Who receives the invoice: the person who signed up or their finance department? How do team members get access without sharing credentials? What happens when someone leaves the team mid-billing-cycle?

Team subscriptions aren't just per-seat pricing multiplied out. They're a different model with distinct concepts: billing owners versus users, seat allocation and limits, and organisational access control.

<!-- IMAGE: Illustration showing one person paying, multiple people accessing
     Placement: hero
     Suggested: Simple visual metaphor of owner vs team members -->

## The Fundamental Split: Who Pays vs. Who Uses

Individual subscriptions conflate two roles that team subscriptions must separate. When a solo user buys a subscription, the same person handles billing and uses the product. When a company buys seats for a team, the person responsible for payment may never log into the product at all.

The billing owner is the person or entity responsible for payment. They receive invoices, manage payment methods, and handle subscription changes. In team scenarios, this is often a finance administrator or procurement team rather than an end user.

Grantees are the people who actually use the product. They log in, access features, and derive value from the subscription. They might not know or care what the subscription costs; they just need access to do their work.

This distinction is fundamental to getting team billing right. As you design each feature and flow, ask yourself: is this for the billing owner or the grantee?

The billing portal, where customers update payment methods and view invoices, is for owners. The product itself is for grantees. The seat management interface, where administrators add and remove team members, sits in between and might serve both audiences depending on your organisational model.

## Modelling Team Structure

Once you've separated billing from access, you need to model how teams actually work. The simplest approach is a flat list of users attached to a subscription. The owner pays, and every grantee in the list has access. This works for small teams with straightforward needs.

More sophisticated products need hierarchical structures. A company might have multiple departments, each needing separate seat pools while sharing a single billing relationship. Or they might need to assign different permission levels within the team: admins who can manage seats, editors who can modify content, and viewers who can only read.

<!-- IMAGE: Diagram showing flat team vs hierarchical team structures
     Placement: diagram
     Suggested: Two contrasting org structures -->

The temptation is to build for the complex case immediately, but this adds significant engineering overhead. Start with the flat model unless you have concrete evidence that customers need hierarchy. Most early team customers will be small enough that a simple list of seats suffices.

Whatever structure you choose, you'll need a way to identify which grantee group a user belongs to. This could be an explicit team ID, an email domain, or a reference to an external identity provider. That identifier connects users to their subscription and determines what they can access.

## Seat Allocation and Limits

Per-seat pricing means tracking how many seats are used and enforcing limits. This sounds simple, but the details matter for both customer experience and revenue.

The first decision is whether seats are allocated or consumed. In an allocation model, the owner explicitly assigns seats to specific users: Alice gets seat one, Bob gets seat two. The seat remains allocated even if the user doesn't log in regularly. This model is straightforward to understand and administer.

In a consumption model, seats are claimed on a first-come, first-served basis up to the limit. Any user with the right invitation or email domain can claim a seat. This model is more flexible but can lead to conflicts when more people want access than seats allow.

The second decision is what happens when limits are reached. The strict approach blocks new users from joining until a seat is freed or more seats are purchased. This protects revenue but creates friction when a team needs to add someone urgently.

The flexible approach allows temporary overage, charging for the additional seat on the next billing cycle or flagging the account for upgrade. This prioritises user experience but requires careful communication to avoid billing surprises.

Most SaaS products adopt a hybrid: hard limits on the subscription quantity, but a self-serve upgrade path that's fast enough that hitting limits doesn't block work. The team lead can add more seats in seconds, making the limit a speed bump rather than a wall.

## Managing Seat Changes Mid-Cycle

Team membership changes constantly. People join companies, leave companies, change roles, and switch teams. Your billing logic must accommodate these changes without creating accounting nightmares or support tickets.

When someone joins a team mid-cycle, you have options. You could charge nothing until the next billing period, effectively giving away free access. You could charge a prorated amount for the remainder of the current period. Or you could charge the full period price regardless of timing.

Proration is the most common approach. If a customer adds a seat halfway through the month, they pay half the monthly seat price. This feels fair and matches customer expectations. The tricky part is presentation: customers should see clear line items that explain the prorated charges.

When someone leaves a team, the question is whether to issue credit. Some products reduce the seat count immediately but don't credit the unused portion. Others prorate a credit that applies to the next invoice. The right answer depends on your pricing and customer expectations.

<!-- IMAGE: Timeline showing seat changes and billing impact
     Placement: inline
     Suggested: Timeline diagram with billing events -->

The simplest implementation is to handle seat changes at the billing cycle boundary. Seats can only be added or removed at renewal, and changes made mid-cycle take effect at the next renewal. This eliminates proration complexity entirely. It works for products where seat changes are infrequent, but frustrates customers who need to add users urgently.

## Invitations and Onboarding

Team members need a way to claim their seats and start using the product. The invitation flow bridges billing and product access, and getting it right shapes your customers' first impression of working with you.

A typical flow works like this: the billing owner or team administrator initiates an invitation by entering email addresses. Your system sends invitation emails with unique links. Recipients click the link, create or connect an account, and join the team. The seat is consumed when they complete onboarding.

Tokens in the invitation link handle most edge cases. The recipient's sign-in email doesn't need to match the invited address—the token validates the invitation, not the email. You'll still want clear handling for expired invitations and users who already belong to another team, but the token-based approach keeps the common path simple.

Some companies want to enforce that team members use their corporate email domain. This is a separate concern from invitations—it's about identity policy, not access flow. If your customer is acme.com, they might require all team members to sign in with @acme.com addresses regardless of how they were invited.

Single sign-on adds another dimension. Enterprise customers often require SSO integration, where their corporate directory manages identity. In these setups, seat allocation can happen automatically based on directory group membership, with no manual invitation required.

## Owners, Grantees, and Multi-Tenancy

In Salable, the hierarchy is simple: an owner can have many groups, and groups can have many grantees. The owner is the top-level tenant—the organisation or account that holds subscriptions. Groups let you organise grantees within that owner, whether that's departments, teams, or any structure that fits your product.

This matters because a single grantee can exist across multiple owners. Someone might have a personal account on your service and also belong to an enterprise organisation with a different subscription tier. When you check entitlements, you pass the granteeId (typically the user ID) and filter by owner to get the capabilities for their current context. Switch tenants, filter by a different owner, and the same user sees different entitlements.

Salable doesn't dictate who can manage subscriptions—that's your RBAC implementation. By making the owner the overarching group, you decide which members should have access to billing, seat management, and admin functions. Some teams want only the original purchaser to manage billing. Others delegate to multiple administrators. Your access control, your rules.

The administrative experience you build depends on your customers. Early customers with five-person teams need something simple. Enterprise customers managing hundreds of users need delegation, bulk operations, and audit logs. Start simple and expand as your customer base demands it.

## How Salable Avoids Common Mistakes

Developers building team subscriptions from scratch hit the same problems repeatedly. Salable's owner/grantee model sidesteps them by design.

Coupling user identity to subscription identity creates problems when subscriptions change hands—the original purchaser's account becomes inseparable from the billing. Salable keeps these separate. The owner holds the subscription; grantees get access through groups under that owner. Transfer ownership, and grantees keep their access without disruption.

The solo-to-team transition trips up many implementations. A solo user upgrades, and suddenly their account needs to become a team with them as a member. With Salable, a solo user is just an owner with one group and one grantee—themselves. Adding team members means adding grantees to a group. No migration, no restructuring.

Hardcoding seat limits in your application makes plan changes painful. Salable treats limits as configuration. Change a plan's seat count in the dashboard, and existing subscriptions reflect it automatically. Your code asks Salable what the limits are; it never stores them locally.

When someone loses access—removed from a team, subscription cancelled—your app still needs to handle that gracefully. Salable makes this simple: check their entitlements, and if they have none, show them why and what they can do about it.

## Building for Growth

Team subscriptions are often the first step toward enterprise features. As your customers grow, they'll request capabilities that go beyond basic seat management.

Hierarchical organisation structures let companies model departments, teams, and sub-teams within a single billing relationship, enabling delegated administration and budget allocation.

Role-based access control restricts what different team members can do within the product. Not everyone needs full access; some users should be viewers, others editors, others admins.

Usage allocation lets teams distribute limits across organisational units. If the subscription includes 100,000 API calls, different departments might have separate quotas.

Audit logging tracks who did what and when, satisfying compliance requirements and enabling security reviews.

You don't need these features at launch. But designing your team model with an eye toward future requirements helps you avoid architectural dead ends. The separation of billing owner from grantee, and the explicit modelling of team membership, creates the foundation that enterprise features build on.

---

_Salable's [owner/grantee model](https://beta.salable.app/docs/grantee-groups) handles the complexity of team subscriptions out of the box. You focus on your product; we'll handle who gets access to it._
