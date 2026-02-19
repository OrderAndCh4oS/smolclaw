---
description: Manage subscriptions for teams, not just individuals. The Grantee and Group system controls who has access, handles seat limits, and keeps everything in sync as teams grow and change. In this guide we cover how to manage team access in your application.
---

# Grantees & Groups

## Overview

Most subscription systems assume one subscription equals one user. But real applications are more complex—teams share access, organisations manage multiple departments, and a single subscription often needs to grant access to many people. Building this yourself means tracking group memberships, managing seat limits, and keeping access in sync as teams grow and change.

The Grantee and Group system solves this. You can manage Subscriptions for entire teams rather than just individuals, add users to Groups before they even purchase, and dynamically allocate seats and manage access. A single Subscription can control access for an entire team, and Grantees can represent any entity in your system—users, boards, workspaces, projects, or whatever makes sense for your application.

## Terminology

### Owners

An **[Owner](/docs/core-concepts#owner)** is an identifier used to scope Subscriptions, Carts, and metered usage in Salable. In your application, this typically represents a user ID for individual Subscriptions, or a company, organisation, team, or project ID for shared Subscriptions where multiple people need access to the same Subscription data.

The Owner ID should be an identifier that anyone who needs to view Subscription data or increment usage meters will have access to. For example, in a team Subscription, all team members who might record usage would share the same Owner ID (like a team or organisation ID). Your application's RBAC determines who has permission to modify or cancel Subscriptions, and your business logic determines who is financially responsible—the Owner ID is simply the scoping mechanism for organising Subscription data in Salable.

Each Owner can own multiple Subscriptions and Grantee Groups. You'll need to provide an Owner when creating Carts and Subscriptions.

### Grantees

**[Grantees](/docs/core-concepts#grantee)** are individual identities that receive access to your application's features. They can represent individual users, boards, workspaces, projects, API keys, service accounts, or any other identifiable entity in your system.

Each Grantee is identified by a `granteeId` that you provide. You can optionally include a display name for easier management in the dashboard. Grantees can belong to multiple Groups, and their access is checked via the `/api/entitlements/check` endpoint.

### Groups

**[Groups](/docs/core-concepts#group)** are collections of Grantees under a single Owner. They serve as the link between Subscriptions and individual access. Each Group belongs to one Owner and can contain multiple Grantees (members). When you create Subscriptions, you attach Plans to Groups rather than individual Grantees. Groups can have an optional name for identification, and one Owner can have multiple Groups—perfect for organisations with different departments or teams.

### Memberships

Memberships are the join records that link Grantees to Groups. Each Membership links one Grantee to one Group, and they're managed automatically when you add or remove Grantees from Groups.

## The Relationship Model

```
Owner (pays for subscription)
  └─ Has many Groups
      └─ Has many Grantees (via Memberships)
      └─ Has many Subscription Plans (with seats)

Subscription
  └─ Belongs to Owner
  └─ Has many Subscription Plans
      └─ Each plan is linked to a Group
      └─ Each plan has a seat count
```

## How Access Works

When you check if a Grantee has access to a feature, Salable follows a straightforward path. First, the system looks up the Grantee by their `granteeId` and finds all Groups they belong to through their Memberships. Then it looks at all Subscription Plans attached to those Groups and checks if any of those Plans include the requested Entitlement. After validating that the Subscriptions are active, it returns the Entitlements along with their expiry dates.

## Common Use Cases

### Individual User Subscriptions

For single-user Subscriptions, the simplest approach is to use the same ID for both Owner and Grantee:

```bash
# Create a Group with the user as both Owner and Grantee
POST /api/groups
{
  "owner": "user_123",
  "name": "User 123's Personal Workspace",
  "grantees": [
    {
      "granteeId": "user_123",
      "name": "John Doe"
    }
  ]
}
```

### Team Subscriptions

For team Subscriptions, create a Group with a team identifier as the Owner:

```bash
# Create a Group for a team
POST /api/groups
{
  "owner": "team_acme",
  "name": "Acme Corp Development Team",
  "grantees": [
    {
      "granteeId": "user_alice",
      "name": "Alice Smith"
    },
    {
      "granteeId": "user_bob",
      "name": "Bob Johnson"
    }
  ]
}
```

### Multi-Team Management

One Owner can manage multiple teams by creating separate Groups for each. This is perfect for larger organisations with different departments:

```bash
# Engineering team
POST /api/groups
{
  "owner": "company_xyz",
  "name": "Engineering",
  "grantees": [...]
}

# Marketing team
POST /api/groups
{
  "owner": "company_xyz",
  "name": "Marketing",
  "grantees": [...]
}
```

## Creating Groups

Groups can be created in two ways: explicitly through the dashboard or API, or automatically during Checkout if you haven't created one yet. Creating a Group beforehand lets you set up team members before purchase.

You can create an empty Group and add members later, or include Grantees from the start.

### API: Create a Group

**Endpoint:** `POST /api/groups`

**Request Body:**

```json
{
    "name": "Development Team",
    "owner": "company_acme",
    "grantees": [
        {
            "granteeId": "user_alice",
            "name": "Alice Smith"
        },
        {
            "granteeId": "user_bob",
            "name": "Bob Johnson"
        }
    ]
}
```

The `grantees` array is optional. When you include Grantees in your request, Salable handles all the entity creation. It creates Owners and Grantees if they don't exist, and establishes Membership records to link Grantees to the Group. If Grantees already exist elsewhere, new Memberships are simply added without duplicating the Grantee records.

**Response:**

```json
{
    "data": {
        "id": "Group_01HXXX",
        "organisation": "org_xxx",
        "ownerId": "Owner_01HYYY",
        "name": "Development Team",
        "createdAt": "2024-01-15T10:00:00Z",
        "updatedAt": "2024-01-15T10:00:00Z"
    }
}
```

### Dashboard: Create a Group

In the dashboard, navigate to **Groups** in the sidebar. You'll see a "Create a Group" form where you can enter a Group name (optional) and an Owner ID (required). Click **Create Group** and you'll have an empty Group ready to go. From there, you can add Grantees individually through the Group management interface.

## Managing Grantees

### Adding Grantees to Groups

You can add Grantees to a Group at any time, whether before or after creating a Subscription.

**API Endpoint:** `POST /api/groups/{groupId}/grantees`

**Request Body:**

```json
[
    {
        "type": "add",
        "granteeId": "user_charlie",
        "name": "Charlie Brown"
    }
]
```

**Dashboard:**
Navigate to **Groups** and click the **Manage Group** icon (eye icon) for the Group you want to modify. You'll see an "Add a grantee" form where you can enter a Grantee name (optional) and Grantee ID (required). Click **Add Grantee** and they'll be added to the Group through a new Membership record.

> **Note** If the Group has per-seat Plans attached, you cannot exceed the allocated seat count.

### Removing Grantees from Groups

Removing a Grantee from a Group is straightforward, but it's important to understand what happens: you're removing their Membership, not deleting the Grantee entirely. The Grantee still exists and can be added back to this Group or to other Groups later.

**API Endpoint:** `POST /api/groups/{groupId}/grantees`

**Request Body:**

```json
[
    {
        "type": "remove",
        "granteeId": "user_charlie"
    }
]
```

**Dashboard:**
Navigate to **Groups**, click **Manage Group**, find the Grantee in the table, and click the **Sign Out** icon. This removes their Membership from the Group while preserving the Grantee record itself.

### Replacing Grantees

Sometimes you need to swap one Grantee for another—like when a team member leaves and someone new joins. Instead of removing one and adding another in separate steps, you can replace them in a single atomic operation.

**API Endpoint:** `POST /api/groups/{groupId}/grantees`

**Request Body:**

```json
[
    {
        "type": "replace",
        "granteeId": "user_old",
        "newGranteeId": "user_new",
        "name": "New User Name"
    }
]
```

This maintains seat limits while rotating access. The old Grantee's Membership is removed and the new one is added simultaneously, keeping your seat count consistent throughout the transition.

### Batch Operations

When you need to make multiple changes at once, batch them in a single API request.

```json
[
    { "type": "remove", "granteeId": "user_1" },
    { "type": "remove", "granteeId": "user_2" },
    { "type": "add", "granteeId": "user_3", "name": "User Three" },
    { "type": "add", "granteeId": "user_4", "name": "User Four" }
]
```

Remove operations are processed first, then add operations. This ordering ensures seat limits are respected—you free up seats before trying to fill them.

## Seat Management

When a Group has per-seat Subscription Plans attached, seat quantity limits how many Grantees can be in that Group.

### How Seats Work

Per-seat **[Line Items](/docs/core-concepts#line-item)** define seat-based pricing, and each Subscription Plan has a quantity that represents the number of seats. When you try to add Grantees to a Group, Salable validates the Group size against the seat count. You cannot add more Grantees than you have seats for. If the Group has multiple Plans with per-seat pricing, the lowest seat count across all Plans becomes the limiting factor.

### Example: Seat Constraints

Imagine a Group called "Acme Dev Team" with 5 current members. The Group has Plan A with 10 seats and Plan B with 7 seats. Since the lowest count is 7, that's the maximum Group size—leaving 2 available seats.

### Viewing Seat Information

In the dashboard, navigate to **Groups**, click **Manage Group**, and look at the **Plans** section. The "Seats" column shows allocated seats for each Plan, and the seat count that's limiting your Group size is shown in bold.

### Increasing Seats

When you need to add more Grantees than your current seat allocation allows, you'll need to increase the seat count first. In the **Plans** section, find the Plan and click the seats icon in the **Actions** column. Enter a new value in the **Seats** field and click **Update Seats**. The seat count is updated via Stripe, and then you can add more Grantees.

**API:**

```bash
PUT /api/plan-items/{subscriptionPlanLineItemId}
{
  "quantity": 15
}
```

### Pre-Purchase Team Setup

One powerful pattern is adding Grantees to Groups before purchasing a Subscription. Create a Group with Grantees, add the Group to a Cart, and when checking out, ensure the quantity matches or exceeds the Group size. After Checkout, all Grantees immediately have access. This approach lets you onboard teams upfront, collect user information before payment, and simplify the post-purchase experience.

## Subscriptions and Groups

### Linking Subscriptions to Groups

Subscriptions are linked to Groups through Subscription Plans. Each Subscription Plan within a Subscription is associated with a specific Group. When adding items to a Cart during Checkout, you can specify which Group should receive access:

```bash
POST /api/carts/{cartId}/items
{
  "planId": "Plan_01HXXX",
  "groupId": "Group_01HYYY"
}
```

If you don't provide a `groupId`, Salable creates a new empty Group automatically.

### Multiple Plans per Group

A single Group can have multiple Subscription Plans from different Subscriptions. For example, your "Engineering Team" Group might have Subscription A with a Pro Plan (10 seats) and Subscription B with an Analytics Add-on (5 seats). The same lowest-seat-count rule applies here—the Group would be limited to 5 members.

### Viewing Group Subscriptions

In the dashboard, navigate to **Groups**, click **Manage Group**, and look at the **Subscriptions** section. You can click the magnifying glass icon to filter Entitlements by Subscription or click the eye icon to view full Subscription details. Via the API, a simple `GET /api/groups/{groupId}` call returns all Subscription Plans linked to the Group.

## Checking Access

### API: Check Entitlements

To check if a Grantee has access to a feature:

**Endpoint:** `GET /api/entitlements/check`

**Query Parameters:**

- `granteeId` (required): The Grantee to check
- `owner` (optional): Filter to Subscriptions owned by this Owner

**Example:**

```bash
GET /api/entitlements/check?granteeId=user_alice
```

**Response:**

```json
{
    "entitlements": [
        {
            "type": "entitlement",
            "value": "advanced_features",
            "expiryDate": "2024-02-15T10:00:00Z"
        },
        {
            "type": "entitlement",
            "value": "priority_support",
            "expiryDate": "2024-02-15T10:00:00Z"
        },
        {
            "type": "meter",
            "value": "api_calls",
            "expiryDate": "2024-02-15T10:00:00Z"
        }
    ],
    "signature": "hex_signature_string"
}
```

### Subscription Status Handling

Entitlements are returned for Subscriptions with these statuses:

- `active`: Subscription is active and paid
- `trialing`: Subscription is in trial period
- `past_due`: Only if the Product setting "Return Entitlements While Past Due" is enabled

### Testing Access in Dashboard

**Dashboard:**

1. Navigate to **Entitlements** → **Check**
2. Enter a **Grantee ID**
3. Optionally enter an **Owner ID** to filter results
4. Click **Check Entitlements**
5. View the results showing all accessible Entitlements

## Group Lifecycle Management

### Updating Groups

**API:** `PUT /api/groups/{groupId}`

**Request Body:**

```json
{
    "name": "Updated Group Name",
    "owner": "updated_owner_id"
}
```

**Dashboard:**

1. Navigate to **Groups** → **Manage Group**
2. Update the "Group Name" or "Owner" fields
3. Click **Save Group**

### Deleting Groups

**API:** `DELETE /api/groups/{groupId}`

**Dashboard:**

1. Navigate to **Groups**
2. Find the Group in the table
3. Click the **Trash** icon
4. Confirm deletion

> **Warning** Deleting a Group will remove all Memberships (Grantees lose access), potentially affect Subscriptions linked to the Group, and cannot be undone.

## Advanced Patterns

### Cross-Team Grantees

A single Grantee can belong to multiple Groups, even across different Owners:

```
Grantee "user_alice"
  ├─ Member of Group "Acme Engineering" (owner: acme_corp)
  └─ Member of Group "Beta Industries Dev" (owner: beta_industries)
```

This enables scenarios like consultants working across multiple clients, shared team members between departments, or multi-organisation access for admins.

**Checking access with Owner filter:**

```bash
# Check Alice's access within Acme Corp
GET /api/entitlements/check?granteeId=user_alice&owner=acme_corp

# Check Alice's access within Beta Industries
GET /api/entitlements/check?granteeId=user_alice&owner=beta_industries
```

### Anonymous to Authenticated Conversion

For applications where users can start without authentication, you can use a temporary Owner ID during the purchase flow and convert it later. Start by creating a Cart with a temporary Owner ID like a session ID. The user completes Checkout without authentication, and a Group is created with that temporary Owner. After the user signs up, you update the Owner to their authenticated ID.

```bash
# After signup, update the Group Owner
PUT /api/groups/{groupId}
{
  "owner": "user_authenticated_123"
}
```

### Handling Team Growth

As teams grow beyond seat limits, you'll want to handle this gracefully. Monitor Group size as it approaches seat limits, notify admins when capacity is reached, provide UI to increase seat counts, and automatically adjust Subscriptions via Stripe. Here's a simple implementation approach:

```javascript
// Check if group is at capacity
const maxSeats = getLowestSeatCount(group.plans);
const currentSize = group.members.length;
const isAtCapacity = currentSize >= maxSeats;

if (isAtCapacity) {
    // Show upgrade prompt or prevent adding members
}
```

## Best Practices

### Seat Management

Ensure your application enforces that seat counts remain equal to or greater than Group size to avoid access issues. Provide tools for customers to monitor their seat utilisation so they can optimise costs and plan for growth. Consider alerting customers before they reach capacity so they can increase seats proactively rather than reactively.

### Context-Aware Access Control

When Grantees belong to multiple organisations, use the `owner` parameter to filter Entitlement checks to the relevant context. This prevents Entitlements from other organisations bleeding through.

### Security

Validate that `granteeId`s match authenticated users to prevent unauthorised access. Never expose internal database IDs (the `id` fields) to end users—use your own identifiers instead. Take advantage of the signature in Entitlement responses to verify authenticity and implement rate limiting on Entitlement checks to protect against abuse.

### Data Consistency

Create Groups before Checkout when possible to have better control over the process. Ensure Cart quantities match Group sizes for seated Plans to avoid validation errors. Handle edge cases where Grantees belong to multiple Groups, and regularly audit Group Memberships and Subscription status to catch any inconsistencies early.

## Troubleshooting

### Grantee Has No Access

When a Grantee should have access but doesn't, work through these checks systematically. First, verify the Grantee exists by calling `GET /api/grantees?groupId={groupId}`. Then check if the Grantee is in any Groups by looking at their Memberships. Do those Groups have active Subscription Plans? Are the Subscriptions in a valid state like active or trialing? Finally, confirm that the Plans include the Entitlement you're checking for.

### Cannot Add Grantee to Group

If you see "This group has reached its maximum number of grantees," you've hit the seat limit. Check the current Group size against seat limits, increase the seat count on per-seat Line Items, or remove existing Grantees before adding new ones.

### Seat Limits Not Matching Expectations

When your Group size limit is lower than you expect, check all Plans attached to the Group. The lowest seat count determines the limit, so increase seats on that Plan or remove it.

### Entitlements Not Updating

If you've changed a Subscription but the Grantee still has (or doesn't have) access, there are a few possible causes. The Subscription status might not have updated yet—wait for the Stripe webhook to process. The Product setting "Return Entitlements While Past Due" might be affecting results. You might be looking at the wrong Grantee or Owner. Or your application cache needs refreshing. To debug, check the raw Entitlement check response, verify Subscription status in the dashboard, confirm Grantee Group Memberships, and review webhook event logs.

## Summary

The Grantee and Group system provides flexible access management for subscription-based applications. Owners scope Subscription data, Groups organise Grantees under those Owners, and Grantees are the individual identities that receive access. Subscription Plans are linked to Groups rather than individual Grantees, and seats control the maximum Group size for per-seat Plans. When checking Entitlements, the system traverses from Grantee to Groups to Subscriptions to Plans.
