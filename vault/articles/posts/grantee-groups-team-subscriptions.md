---
title: 'Grantee Groups: Team Subscriptions Done Right'
description: "Per-seat pricing gets complicated when the person paying isn't the person using. Grantee groups model the relationship between billing owners, access recipients, and team membership explicitly."
publishedAt: 2026-02-06
category: Beta Features
author: sean-cooper
tags:
    - teams
    - subscriptions
    - features
    - grantee-groups
draft: false
featured: false
---

# Grantee Groups: Team Subscriptions Done Right

<!-- IMAGE: Diagram showing relationship between owner, group, and grantees
     Placement: hero
     Suggested: Visual hierarchy of billing owner, grantee group, and team members -->

Per-seat pricing sounds simple until you implement it. Who pays and who uses aren't the same question. A company administrator buys 50 seats, but the individual team members need access. Adding someone to the subscription shouldn't require the billing owner to click buttons in your UI. And what happens when someone leaves the team? Grantee groups model these relationships explicitly. The owner holds the billing relationship, the grantees receive access, and the group manages membership. Changes propagate automatically, seat limits enforce themselves, and your code doesn't need to track who paid for whom.

The complexity sneaks up on you. Early customers are individuals who buy subscriptions for themselves, so the payer and the user are the same person. Your authentication checks if the current user has a subscription, and everything works. Then a team signs up. The CTO purchases a subscription for their engineering department. Ten engineers need access, but only the CTO has a billing relationship with you. Your authentication logic breaks because the engineers don't have subscriptions in their names.

The quick fix is custom code. You create a mapping table that says "these ten user IDs belong to this subscription." You check that table during authentication. It works until the team grows to twenty, someone leaves, and the CTO asks why they're still paying for departed employees. Now you need admin interfaces for the CTO to manage team membership, and your subscription logic is scattered across multiple systems.

Grantee groups solve this properly from the start. The concepts are distinct and the relationships are explicit, which means your code stays simple even as team complexity grows.

## The Three-Part Model

Understanding grantee groups requires distinguishing three concepts that traditional billing systems conflate: owners, grantees, and groups.

The **owner** identifies who holds the subscription—typically an organisation ID, team ID, or user ID from your system. This is the identifier your application passes when looking up subscription status or recording metered usage. It represents whoever is responsible for the billing relationship: the company that purchased, the team that subscribed, or the individual user. When subscriptions renew, cancel, or upgrade, the owner is the party involved.

**Grantees** are the individuals who receive access to your product through the subscription. They don't have their own billing relationship; instead, they derive access from membership in a group that's associated with the subscription. A grantee might be an employee using company-licensed software, a team member added by an administrator, or a collaborator invited to a shared workspace.

The **group** connects owners and grantees. It's the container that holds grantees and associates with subscriptions. When you check whether a user has access to a feature, you're really asking whether they're a grantee in a group that has an active subscription with the appropriate entitlements.

<!-- IMAGE: Entity relationship diagram showing owner, group, grantee, and subscription
     Placement: diagram
     Suggested: Technical diagram showing the data model relationships -->

This separation might seem like unnecessary complexity, but it reflects how teams actually work. The person with the corporate credit card isn't the same as the people using the product. The list of users changes more frequently than the billing relationship. And the same owner might have multiple groups with different subscriptions for different purposes.

## How Access Flows Through the System

When a grantee tries to access a feature, the access check follows a clear path: retrieve the groups the grantee belongs to, find the subscriptions associated with those groups, and check whether any of those subscriptions include entitlements for the requested feature.

In practice, this means your authentication middleware calls a single function with the grantee's ID and the entitlement they need. Salable handles the traversal from grantee to groups to subscriptions to entitlements and returns a yes or no answer. Your code doesn't need to understand the relationship model; it just asks "can this user do this thing?" and gets a definitive response.

This design scales elegantly. A grantee might belong to multiple groups, perhaps their department group and a cross-functional project group. Each group might have different subscriptions with different entitlements. The access check considers all paths and grants access if any valid path exists.

The performance implications are handled at the infrastructure level. Salable caches the relationship graph so that access checks are fast even for complex group structures. When group membership changes, the cache updates automatically. You don't need to implement caching logic or worry about stale permissions.

## Managing Team Membership

The owner needs to control who belongs to their group, but that control shouldn't require navigating your billing interface for every change. Grantee groups support self-service membership management through APIs and embeddable components.

The simplest pattern is an invitation flow. The owner generates an invitation link or enters email addresses. Invited users accept and become grantees in the group. No manual provisioning on your side, no webhook handlers to map users to subscriptions, no administrative overhead.

For organisations with existing identity providers, grantee groups can sync with external directories. When an employee joins or leaves in the company's HR system, their group membership updates accordingly. The billing subscription doesn't change; only the list of grantees who derive access from it does.

<!-- IMAGE: Team management interface showing members and available seats
     Placement: inline
     Suggested: Screenshot of a grantee management UI with seat counts -->

Seat limits enforce themselves through the group. If a subscription includes 50 seats, the group can have at most 50 grantees. Attempting to add more fails with a clear error indicating the seat limit. The owner can either remove existing grantees or upgrade their subscription to add more seats. This enforcement happens at the group level, not in your application code.

## Handling Complex Organizational Structures

Real organisations rarely fit a simple hierarchy. Departments, teams, projects, and temporary working groups create overlapping structures that traditional per-seat billing can't model.

Grantee groups handle this complexity through multiple groups per owner and multiple group memberships per grantee. A company might have a department-level group for standard access and project-specific groups for specialized features. An employee belongs to their department group and gets added to project groups as needed. Each group can have its own subscription or share entitlements, depending on how you structure your plans.

Consider an enterprise with three departments, each needing your product. Rather than one massive subscription, they might prefer three separate subscriptions with independent billing, budgeting, and administration. Three groups, three subscriptions, one owner at the corporate level. Department administrators manage their own grantees without accessing other departments' groups.

Alternatively, a company might want unified billing but department-level usage tracking. One subscription, three groups, with reporting segmented by group. The billing administrator handles payments while department managers handle membership. The flexibility is in how you model the relationships, not in custom code you write.

## The Developer Experience

For engineering teams implementing team subscriptions, grantee groups dramatically simplify the integration. The Salable SDK provides methods for the common operations: checking access, managing grantees, creating invitations, and querying group membership.

Access checks are the most frequent operation and the simplest to implement. A single API call returns whether a grantee has a specific entitlement through any of their group memberships. You don't need to understand the underlying subscription structure; the answer is already resolved.

```javascript
const hasAccess = await salable.entitlements.check({
    granteeId: currentUser.id,
    entitlement: 'advanced-analytics'
});
```

For administrative interfaces, the SDK provides methods to list group members, add and remove grantees, and check available seat capacity. These power the team management UI that owners use, whether you build custom interfaces or embed Salable's components.

When subscriptions change, webhooks notify your application. A new subscription might mean creating a group. An upgrade might mean increased seat capacity. A cancellation might mean revoking access. These events arrive in real-time, allowing your application to respond immediately rather than polling for changes.

## Migrating Existing Team Implementations

If you already have team subscriptions with custom membership logic, migrating to grantee groups means mapping your existing data model to the new concepts.

The migration typically involves three steps. First, identify your current owners, those who have billing relationships in your system. Create corresponding owners in Salable with the same identifiers. Second, create groups for each team structure you're currently tracking manually. Third, add your existing team member mappings as grantees in the appropriate groups.

<!-- IMAGE: Migration flowchart from custom implementation to grantee groups
     Placement: diagram
     Suggested: Before/after showing database tables mapping to grantee group concepts -->

Once migrated, you can remove your custom membership tables and the code that queries them. Access checks route through Salable instead of your database. Team management happens through the grantee group interfaces instead of your admin panels. The reduction in custom code translates directly to reduced maintenance burden.

For gradual migration, you can run both systems in parallel during a transition period. Check your existing tables first and fall back to grantee groups, or vice versa. This approach lets you validate the new system before fully committing.

## Scaling to Enterprise

Grantee groups aren't just for small teams; they're designed to handle enterprise scale. Organisations with thousands of employees and complex hierarchies use the same primitives as ten-person startups. The difference is in configuration, not code.

Bulk operations handle large-scale changes efficiently. Importing hundreds of grantees from a CSV or syncing thousands of users from an identity provider happens through optimised bulk APIs rather than individual requests. The system is built for enterprise data volumes.

Security controls at the group level let you implement principle of least privilege. Different groups can have different entitlements, and users only receive the entitlements from groups they belong to. Removing someone from a high-privilege group immediately revokes those entitlements even if they remain in other groups.

## The Simplicity of Explicit Relationships

The fundamental insight behind grantee groups is that explicit modeling beats implicit inference. When relationships between payers, users, and access are explicit in your data model, everything else gets simpler. Access checks become lookups rather than computations. Team management becomes data updates rather than business logic. Scaling becomes capacity rather than architectural rework.

Your application code asks simple questions and gets simple answers. Can this user access this feature? Yes or no. How many seats are available in this group? A number. Who are the members of this group? A list. The complexity of team subscriptions is handled in the infrastructure where it belongs, not scattered throughout your application.

Per-seat pricing still sounds simple, because with grantee groups, it actually becomes simple. The billing owner, the access recipients, and the group that connects them are all first-class concepts with explicit relationships. Your implementation reflects reality instead of working around a data model that assumes every payer is also a user.

The CTO who buys 50 seats can manage their team without understanding your billing system. Engineers get access without needing subscription records in their names. And when someone leaves, removing them from the group is all it takes. The subscription continues, the seat frees up, and the access revokes automatically. That's team subscriptions done right.
