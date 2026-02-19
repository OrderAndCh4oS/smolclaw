---
title: 'Implementing Board-Based Access Control in Miro'
description: "Miro users live in boards. Your plugin's access control should probably follow this pattern, granting access at the board level rather than forcing individual user subscriptions."
publishedAt: 2026-05-05
category: Monetising Miro Apps
author: sean-cooper
tags:
    - miro
    - access-control
    - integration
    - billing
draft: false
featured: false
---

Miro users live in boards. They create boards, share boards, and collaborate on boards. Your plugin's access control should probably follow this pattern, granting access at the board level rather than forcing individual user subscriptions. But board-based access raises questions that user-based billing doesn't: who pays for a shared board? What happens when a board is duplicated? How do you handle boards that move between teams? Implementing board-scoped subscriptions requires understanding Miro's identity model and designing access checks that feel natural to how people actually use Miro.

Getting access control right matters beyond billing correctness. Clunky access patterns frustrate users and generate support tickets. Overly restrictive controls push collaborators toward workarounds that undermine your value proposition. The goal is access logic that feels invisible when it works, gating premium functionality in ways that match users' mental models of how they should pay for your plugin.

## Miro's Identity Model

Before designing access control, you need to understand how Miro identifies users, boards, and the relationships between them. Miro's data model has nuances that affect how you implement subscription checks.

Users in Miro have unique identifiers that persist across teams and organisations. When someone accesses your plugin, you can retrieve their user ID through the Miro SDK and use it to check entitlements. User-based access control maps subscriptions to these IDs, granting access to anyone whose ID appears in your subscriber records.

Boards also have unique identifiers and exist within the context of teams. Each board has an owner, the user who created it, and may have collaborators with various permission levels. When your plugin runs on a board, you can access both the board ID and information about the current user's relationship to that board.

Teams aggregate users and boards within organisations. A user might belong to multiple teams, and teams can have different subscription states if you choose to implement team-level access control. Miro's API lets you query team membership and understand the organisational context in which your plugin operates.

The question is which of these entities should anchor your subscription model. User-based access means each person who wants to use your plugin needs their own subscription or a seat in someone else's plan. Board-based access means the subscription attaches to the board, and anyone collaborating on that board gets access. Team-based access grants plugin functionality to everyone in a subscribed team.

## Why Board-Based Access Makes Sense

For many Miro plugins, board-based access control creates the smoothest user experience. Miro's collaboration model assumes that everyone working on a board can contribute equally. When your plugin requires individual subscriptions, you create friction that breaks this model. Half the team can use your plugin while the other half can't, which either limits collaboration or forces someone to purchase seats for everyone.

Board-based access aligns your billing with how Miro users think about ownership. The person who creates a board typically takes responsibility for it, including the tools that make that board functional. If they've subscribed to your plugin for their boards, collaborators benefit without needing to understand your billing model.

Consider a workshop facilitation plugin used during team meetings. The facilitator creates a board, sets up the workshop structure, and invites participants. Under user-based access, either every participant needs a subscription, or only the facilitator can interact with premium features while participants watch. Under board-based access, the facilitator's subscription covers the board, and everyone can participate fully. The second model matches how facilitation actually works.

Board-based access also simplifies your sales motion. You're not asking organisations to count how many people might use your plugin and buy that many seats. You're asking them to subscribe for the boards where they need your functionality. If they use Miro heavily, they'll have many boards and potentially need multiple subscriptions. If they use it lightly, a single subscription might cover their needs.

## Implementing Board-Level Checks

The core implementation pattern checks the board owner's subscription status whenever your plugin loads. Retrieve the current board's ID and owner information through Miro's SDK, then query your subscription system to determine whether that owner has active entitlements for your plugin.

Your plugin's initialisation code should perform this check early, before rendering any premium UI. If the board owner lacks a subscription, show an appropriate message: perhaps a preview of what the plugin offers, information about how to subscribe, and graceful degradation that doesn't leave users confused about why functionality is missing.

Caching subscription status reduces API calls and improves performance, but cache invalidation requires thought. When someone subscribes, you want their boards to gain access immediately, not after cache expiration. When someone cancels, you need to revoke access within a reasonable timeframe. Webhooks from your billing system can trigger cache invalidation, ensuring subscription changes propagate without excessive polling.

Handling board ownership changes adds complexity. If a subscribed user creates a board and later transfers ownership to someone without a subscription, does access persist or revoke? There's no universally right answer, but you need a defined policy. Allowing continued access until the subscription renews (or fails to renew) reduces disruption. Revoking immediately matches strict interpretation of "owner's subscription" but may surprise users.

Board duplication creates similar questions. When someone duplicates a board that had premium plugin functionality enabled, should the duplicate retain access? If the original owner also owns the duplicate, yes. If someone else duplicates the board to their own account, the access state should depend on the new owner's subscription status. Miro's duplication events let you detect these scenarios and adjust your access records accordingly.

## Mapping Miro Identities to Your Billing System

Your billing system needs to understand Miro users so subscription checks can succeed. The mapping between Miro's identity model and your subscriber records requires careful design.

The simplest approach stores Miro user IDs directly as subscriber identifiers. When someone subscribes through your checkout flow, capture their Miro user ID and associate it with the subscription. Access checks then query whether the board owner's Miro ID has an active subscription.

Enterprise customers may need more sophisticated identity mapping. If they manage subscriptions centrally rather than having individuals subscribe, you need a way to associate their organisation's subscription with multiple Miro users. This typically involves capturing the Miro team or organisation ID and granting access to all members of that team.

Entitlement systems provide a layer of abstraction between subscriptions and access checks. Rather than querying subscription status directly, you query whether a specific user or board has a specific entitlement. The billing system manages the connection between subscriptions and entitlements, handling complexity like trial periods, plan changes, and grace periods after failed payments.

Platforms like Salable model entitlements explicitly, letting you define access rights that your plugin checks without needing to understand the underlying subscription mechanics. A board-based access implementation would check whether the board owner has the appropriate entitlement for your premium features. Salable handles the complexity of mapping subscriptions to entitlements, leaving your plugin code focused on the access check itself.

## Handling Edge Cases Gracefully

Board-based access control encounters edge cases that user-based billing doesn't face. Anticipating these scenarios and designing graceful handling prevents confusion and support escalations.

Guest collaborators in Miro might not have full Miro accounts. If your access check depends on retrieving user IDs, guests can create complications. Decide whether guest access to your plugin follows the board owner's subscription (probably yes) and ensure your access logic handles the case where collaborator identity information is incomplete.

Boards shared across teams can have ambiguous ownership in practice, even if Miro's data model is clear. A consultant might create a board in a client's team, then transfer ownership when the engagement ends. Your access logic should handle these transitions without requiring manual intervention.

Failed payments need grace periods that match Miro users' expectations. Revoking access immediately when a credit card fails creates a poor experience for someone in the middle of a workshop. Providing a few days of continued access while payment issues resolve feels more appropriate. Configure your billing platform to support grace periods and ensure your access checks respect them.

Free trials for board-based access need scoped carefully. Do new boards a user creates during their trial get access? Do existing boards retroactively gain access? What happens to content created during the trial if the user doesn't convert? Having clear policies, communicated to users upfront, prevents surprises that damage trust.

## Testing Your Access Control

Access control implementations have failure modes that only appear in specific scenarios. Thorough testing before launch catches issues that would otherwise frustrate users.

Test the basic flow first: a subscribed user's boards have access, an unsubscribed user's boards don't. Verify that access checks happen at the right time, before users attempt to use premium features rather than after. Confirm that your access-denied experience is clear and actionable.

Test subscription lifecycle events: new subscriptions grant access immediately, cancellations revoke access appropriately, plan changes update entitlements correctly. If you support multiple tiers with different feature sets, verify that tier changes reflect in access checks.

Test collaborative scenarios: subscribed owner with unsubscribed collaborators, unsubscribed owner with subscribed collaborators, boards transferred between users with different subscription states. These scenarios reveal assumptions in your access logic that might not hold.

Test error conditions: what happens when your billing system is unreachable, when Miro's API returns unexpected data, when cached subscription status is stale. Graceful degradation during errors, whether that's allowing access temporarily or showing a helpful error message, matters for user experience during failures.

Board-based access control reflects how Miro users think about collaboration and ownership. Implementing it correctly requires understanding Miro's identity model, designing access checks that feel natural, and handling edge cases that inevitably arise when boards are shared, duplicated, and transferred. The investment pays off in smoother user experiences and fewer support tickets about who needs to pay for what.
