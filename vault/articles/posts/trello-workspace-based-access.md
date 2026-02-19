---
title: 'Implementing Workspace-Based Access for Your Trello Power-Up'
description: 'Most successful paid Power-Ups scope access at the workspace level because it matches how teams think about tool budgets. The workspace administrator purchases, and everyone benefits.'
publishedAt: 2026-04-14
category: Monetising Trello Apps
author: sean-cooper
tags:
    - trello
    - access-control
    - integration
    - billing
draft: false
featured: false
---

# Implementing Workspace-Based Access for Your Trello Power-Up

When a customer subscribes to your Power-Up, who gets access? The individual user? Everyone on the board? The entire workspace? Trello's permission model gives you flexibility, but that flexibility can become confusion if you don't design access control intentionally. Most successful paid Power-Ups scope access at the workspace level because it matches how teams think about tool budgets. The workspace administrator purchases, and everyone in the workspace benefits. Implementing this pattern requires understanding how Trello identifies workspaces and how to sync that identity with your subscription system.

<!-- IMAGE: Diagram showing Trello's hierarchy of workspace > boards > cards with subscription access flowing down from the workspace level
     Placement: hero
     Suggested: Hierarchical tree diagram with workspace at the top, multiple boards below, and the subscription scope highlighted at the workspace level -->

## Understanding Trello's Organisational Hierarchy

Trello organises content in a clear hierarchy that your access control needs to respect. At the top sit workspaces, which Trello's API calls organisations. Workspaces contain boards, boards contain lists, and lists contain cards. Each level has its own membership, but the membership at higher levels influences what's possible at lower levels.

Workspace membership defines who can participate in that workspace's boards. A workspace might have fifty members, but any individual board might include only a subset of those members. This flexibility helps large organisations manage access, but it creates questions for Power-Up developers about which level should govern billing.

The workspace level makes the most sense for subscription access because it matches how organisations budget for tools. A department head or team lead decides that their workspace needs your Power-Up, subscribes at the workspace level, and everyone working within that workspace benefits. Individual board membership might fluctuate, but workspace membership represents the stable unit that aligns with cost centres and approval authority.

Board-level billing creates friction that workspace billing avoids. If access were board-specific, users would need to manage separate subscriptions for each board, or you'd need to build complex logic to determine which boards are covered. When someone creates a new board, does it automatically get access? What happens when a subscribed board is copied? Workspace-level billing sidesteps these questions entirely: if the workspace is subscribed, all boards within it have access.

## Trello's Identity Model for Developers

The Trello Power-Up platform exposes identity information that your application needs to make access decisions. Understanding what's available and how to retrieve it reliably forms the foundation of your access control implementation.

Every Trello workspace has a unique identifier that persists for the life of that workspace. This ID doesn't change when the workspace is renamed, when membership changes, or when boards are added or removed. Your billing system should use this ID as the primary key for workspace subscriptions because it provides stable identity across all the changes workspaces undergo.

The Power-Up client library provides the `t.organization()` method to retrieve the current workspace context. When your Power-Up runs on a board, this method returns the organisation object containing the workspace ID, name, and other metadata. Note that Trello uses "organisation" and "workspace" somewhat interchangeably in its API; they refer to the same concept.

User identity comes through `t.member()`, which returns the currently authenticated Trello user. You'll need this to log events, personalise experiences, and potentially for user-level access decisions within a workspace subscription. The combination of workspace ID and user ID gives you complete context about who is using your Power-Up and in what context.

Board identity via `t.board()` provides the specific board where your Power-Up is running. While you won't typically bill at the board level, you may need board context for feature decisions, logging, or workspace validation. A board always belongs to exactly one workspace, and the workspace ID is accessible from the board context.

<!-- IMAGE: Code-style diagram showing the relationship between t.organization(), t.member(), and t.board() calls and the data each returns
     Placement: inline
     Suggested: Visual representation of the three API calls with sample response data showing IDs and relationships -->

## Mapping Trello Identity to Your Subscription System

Your subscription system needs to answer a simple question quickly: does the current context have access to paid features? The implementation involves mapping Trello's workspace identity to your subscription records and checking that mapping on every Power-Up interaction.

When a workspace administrator completes a subscription through your billing flow, you create a subscription record keyed to their Trello workspace ID. This record might also store the subscribing user's ID for reference, the subscription tier, seat count limits, and billing metadata. The workspace ID is the critical field because all subsequent access checks will use it.

Access checking happens when your Power-Up initialises and potentially on specific user actions. The basic flow retrieves the current workspace ID from Trello's client library, queries your subscription system for a record matching that ID, and returns full or limited functionality based on whether an active subscription exists.

The latency of this check matters for user experience. Users shouldn't wait seconds to see whether they have access to features. Caching subscription status locally with a reasonable time-to-live reduces API calls while maintaining accuracy. A five-minute cache means access changes propagate within five minutes, which is acceptable for most use cases.

Webhook integration improves responsiveness for subscription changes. When your billing system processes a new subscription, cancellation, or renewal, it can proactively push updated status to your Power-Up's backend. Your Power-Up can then invalidate caches and reflect changes immediately rather than waiting for cache expiration.

## Handling Workspace Members and Seat Counts

Workspace-level billing often includes per-seat pricing, which requires tracking how many users exist in the subscribed workspace. This tracking involves syncing with Trello's membership data and enforcing limits when seat counts are exceeded.

Trello's API provides workspace membership lists through the organisations endpoint. You can retrieve all members of a workspace, including their roles and basic profile information. This data helps you display seat usage to administrators and enforce seat limits on access.

Seat counting approaches vary by business model. Some Power-Ups count all workspace members as seats, charging for anyone who could potentially use the Power-Up. Others count only users who have actually interacted with the Power-Up within a billing period. The first approach is simpler and provides predictable billing; the second feels fairer but requires tracking usage at the user level.

When seat counts exceed subscription limits, you have several options. The strictest approach blocks additional users from accessing the Power-Up until the subscription is upgraded. A gentler approach allows access but displays upgrade prompts to administrators. The most permissive approach allows temporary overages with automatic billing adjustments, though this requires customer agreement and sophisticated billing integration.

Proactive seat monitoring helps administrators manage their subscription before hitting limits. Dashboard views showing current seat usage versus subscription limits, email alerts when usage approaches thresholds, and easy upgrade paths all improve the customer experience while encouraging appropriate tier selection.

<!-- IMAGE: Dashboard mockup showing seat count monitoring with current usage, limit, and upgrade prompt
     Placement: inline
     Suggested: Clean UI showing "8 of 10 seats used" progress bar with workspace member avatars and upgrade call-to-action -->

## Synchronising Membership Changes

Trello workspace membership changes continuously as team members join and leave. Your subscription system needs to reflect these changes without manual intervention from administrators.

Trello webhooks provide real-time notification of membership changes. You can register a webhook on a workspace that fires when members are added or removed. When these events occur, your backend receives the notification and can update seat counts, adjust billing, or revoke access as appropriate.

The webhook payload includes the affected user's ID and the action taken. For member additions, you increment your seat count and check against subscription limits. For member removals, you decrement the count and potentially trigger refund calculations if you process seat reductions mid-cycle.

Webhook reliability requires handling retries and idempotency. Trello may send the same webhook multiple times if your endpoint doesn't respond successfully. Your backend should store enough state to recognise and safely ignore duplicate events. Processing the same member-added event twice shouldn't add two seats to your count.

Periodic reconciliation catches any events that webhooks might miss. A daily job that compares your recorded seat counts against Trello's actual membership ensures consistency. If discrepancies exist, you can investigate whether webhooks failed or your processing logic has bugs, and correct the counts appropriately.

## Handling Edge Cases in Access Control

Real-world usage generates scenarios that simple access control logic doesn't anticipate. Designing for these edge cases upfront prevents confused customers and support burden later.

Users who belong to multiple workspaces create complexity when access differs between workspaces. If someone is a member of both a subscribed and an unsubscribed workspace, which experience do they see? The answer depends on context: when they're working in the subscribed workspace, they see paid features; when in the unsubscribed workspace, they see the limited version. Your Power-Up always checks the current workspace context, not the user's global subscription status.

Workspace transfers, where a board moves from one workspace to another, change the access context. A board that had access because its original workspace was subscribed loses access when transferred to an unsubscribed workspace. Users might be surprised by this change, so consider displaying clear messaging when access is lost due to workspace changes.

Administrator departures raise questions about subscription continuity. If the user who originally subscribed leaves the workspace, does the subscription continue? It should, because the subscription belongs to the workspace, not the individual. However, you may need to transfer administrative rights to a remaining workspace admin so someone can manage billing, handle upgrades, or cancel if needed.

Trial subscriptions scoped to workspaces need clear boundaries. When a workspace's trial expires, all members lose access simultaneously. This shared fate can be jarring if not communicated well. Warning all workspace members before trial expiration, not just the administrator who started the trial, reduces surprise and improves conversion.

<!-- IMAGE: Flowchart showing access decision logic with different paths for subscribed workspace, unsubscribed workspace, trial status, and edge cases
     Placement: diagram
     Suggested: Decision tree diagram with clear yes/no paths and resulting access states -->

## Implementing the Technical Foundation

The technical implementation connects Trello's client-side context with your server-side subscription logic. A typical architecture involves client-side access checks for immediate UI decisions and server-side validation for sensitive operations.

On the client side, your Power-Up code retrieves workspace context and makes an API call to your backend to determine access level. The response indicates whether the workspace has an active subscription, what tier applies, and any limits or restrictions. Your Power-Up stores this response briefly and uses it to decide which features to enable.

Server-side access enforcement prevents circumvention of client-side checks. Any sensitive operation, like exporting data, triggering automations, or accessing premium integrations, should validate subscription status on your backend before proceeding. Client-side checks provide good user experience; server-side checks provide actual security.

Token management connects your backend to Trello's API for membership queries and webhook registration. When a user authorises your Power-Up, you receive tokens that allow API access on their behalf. Store these tokens securely and use them to query membership data when needed for billing reconciliation.

Error handling deserves careful attention. Network failures, API outages, and unexpected responses can disrupt access checks. Decide how your Power-Up behaves when it can't verify subscription status. A generous approach grants temporary access and retries; a strict approach denies access until verification succeeds. The right choice depends on your risk tolerance and the consequences of unauthorised access.

## How Salable Simplifies Workspace Access

Salable's grantee groups model maps directly to Trello's workspace concept, eliminating most of the implementation complexity described above. When you connect Salable to your Trello Power-Up, workspace IDs become grantee group identifiers, and all membership and access logic flows naturally.

Creating a workspace subscription in Salable creates a grantee group keyed to that workspace's Trello ID. All workspace members automatically inherit access through this group membership. Your Power-Up checks entitlements through Salable's API, receiving clear responses about what the current workspace can access.

Seat management happens automatically when you integrate Salable with Trello's membership data. As workspace members change, seat counts update without intervention. Prorated billing, seat limits, and overage handling follow the rules you configure in Salable's dashboard rather than custom code in your backend.

The integration handles edge cases that would otherwise require careful implementation. Workspace transfers, administrator changes, and membership synchronisation all work correctly because Salable understands the Trello identity model. You focus on building Power-Up features while Salable handles the billing and access infrastructure.

## Building for Scale from the Start

Scope subscriptions to Trello workspaces, not boards or users. Workspace billing matches how teams budget and reduces friction when boards are created or archived. The workspace ID provides stable identity for your subscription records, and workspace membership changes are trackable through Trello's API and webhooks.

Design your access check to be fast and reliable. Cache subscription status to avoid API latency on every interaction, but ensure caches refresh quickly enough that access changes propagate within minutes. Use server-side enforcement for any operation where circumvented access checks could cause harm.

Plan for the edge cases that real usage inevitably generates. Multi-workspace users, workspace transfers, administrator departures, and trial expirations all require intentional handling. Addressing these scenarios upfront prevents customer confusion and reduces support burden.

The workspace-based access model scales naturally as your Power-Up grows. Small teams with a single workspace need the same underlying logic as enterprises with dozens of workspaces. Building the correct foundation means growth brings only good problems: more subscriptions, more revenue, more opportunity to invest in the features that drive that growth.
