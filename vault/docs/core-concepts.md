---
description: This reference covers the core terminology in Salable. From products and plans to entitlements and grantee groups, each concept is explained to help you understand how the pieces fit together and get up and running quickly.
---

# Core Concepts

## Foundational Concepts

### Test Mode vs Live Mode

Salable operates in two distinct environments to support safe development and testing. When you're working in Test Mode, you'll never process real money transactions. Instead, you'll use separate test API keys and Stripe's test cards for checkout, making it perfect for development and integration testing. Once you're ready to go live, you'll switch to Live Mode, which uses separate live API keys and processes real payments. Keep in mind that Live Mode requires you to complete Stripe's onboarding process before you can start accepting real payments in production.

---

## Pricing Hierarchy

### Product

Think of a Product as the top-level container representing what you're selling—whether that's a SaaS application or a service offering. It's the vehicle for defining your entire pricing model. Each Product contains one or more Plans and includes basic information like a name, description, and various settings that control how your pricing works.

### Plan

A Plan is a bundle of offerings, services, feature sets, or tiers set at the payment model you define. Think of it as a flexible container that brings together all the pricing components for a specific Subscription option—whether that's your Basic tier, Pro tier, an Analytics Add-on, or any other offering you want to sell.

Each Plan belongs to exactly one Product and can contain one or more Line Items with different pricing models. This is where Salable's real power shines: you can mix flat fees, per-seat charges, usage-based pricing, and one-time fees all within a single Plan. Want a base Subscription fee plus per-user pricing plus metered API calls? No problem—just add those Line Items to your Plan.

Plans are the purchasable entities in your app—when a customer subscribes, they're subscribing to a Plan. Line items within a Plan can be configured with different billing intervals and frequencies. When a customer adds a Plan to their cart, they specify an interval (like "month") and a value (like "1" for monthly or "3" for quarterly). If a currency is provided, Salable cherry-picks only the Line Items that match the requested interval, value, and currency combination. This flexibility means you can design sophisticated pricing models without creating dozens of separate Plans for each variation.

### Line Item

Line items are the individual pricing components that make up a Plan. You can combine multiple Line Items within a single Plan to create sophisticated pricing models. Each Line Item can be configured with different billing intervals and values, giving you tremendous flexibility in how you structure your pricing.

There are four types of Line Items you can use:

**Flat Rate** charges a fixed amount every billing cycle, regardless of usage. This is perfect for base Subscription fees—for example, a $29/month platform fee that every subscriber pays.

**Per-Seat** pricing multiplies the charge by the number of users, licenses, or seats. You might charge $10 per user per month, and you can set minimum and maximum quantities. Per-seat Line Items also support tiered pricing, so you can offer volume discounts as teams grow.

**Metered** pricing is usage-based—you bill customers based on what they actually use during the billing period. Think $0.01 per API call or $0.05 per GB of storage. These Line Items use slugs for tracking usage across billing periods.

**One-Time** charges happen just once and never recur. These are ideal for setup fees or installation charges—like a $99 onboarding fee that's billed only when someone first subscribes.

### Price

A Price represents the actual monetary value and configuration for a Line Item in a specific currency. Each Line Item can have Prices in multiple currencies, and each Price includes the amount, currency, and billing scheme details.

You can modify Prices at any time, but here's the important part: existing Subscriptions will continue using the Price version they started with. They won't automatically update to new pricing unless you explicitly move them. This gives you complete control over whether to grandfather existing customers on old pricing or migrate everyone to your new rates.

### Interval

The interval defines the billing frequency unit—day, week, month, or year. When combined with an interval value (a multiplier), you can create any billing frequency you need. For example, an interval of "month" with a value of 1 means monthly billing, but change that value to 3 and you have quarterly billing. Similarly, "week" with a value of 2 creates biweekly billing.

When customers add a Plan to their cart, they specify the interval and optionally the interval value (which defaults to 1 if not provided). Salable then cherry-picks only the Line Items from that Plan that match the requested combination. Intervals also affect how proration is calculated when Subscription changes occur mid-cycle.

### Currency

Currency represents the monetary unit for pricing and billing. How currency works depends on whether you specify it when creating a cart.

**When you provide a currency**: Salable cherry-picks only the Line Items from the Plan that have Prices in that specific currency and interval combination. This lets you create region-specific pricing models—for example, different Line Items or pricing structures for USD vs EUR customers.

**When you don't provide a currency (geolocation mode)**: Stripe automatically detects the customer's location and displays the appropriate currency. For this to work smoothly, every Line Item in the Plan must have the same default currency, and each Line Item should have Prices for every currency you want to support. If the defaults don't match, the checkout link will error. If a Line Item is missing a Price for a specific currency, that Line Item will fall back to its default currency. In this mode, all Line Items are used—no cherry-picking occurs.

---

## Access Control

### Owner

An owner is an identifier used to scope Subscriptions, carts, and usage records in Salable. This is typically a user ID for individual Subscriptions, or a team or organization ID for shared Subscriptions where multiple people need access to the same Subscription data.

The owner ID should be an identifier that anyone who needs to view Subscription data or increment usage meters will have access to. For example, in a team Subscription, all team members who might record usage would share the same owner ID (like a team or organization ID). Your application's RBAC determines who has permission to modify or cancel Subscriptions, and your business logic determines who is financially responsible—the owner ID is simply the scoping mechanism for organizing Subscription data in Salable.

You'll need to provide an owner when creating carts and Subscriptions, though you can update it later—which is useful when converting anonymous sessions to authenticated user IDs after signup. A single owner can have multiple Subscriptions and grantee groups, and you can filter entitlement checks by owner to scope results appropriately.

### Grantee

A grantee is any entity that receives access to features or entitlements through a Subscription. Grantees are identified by unique IDs from your system—a granteeId that's just a string you provide. These can represent users, teams, projects, boards, workspaces, or any other entity in your application that needs access to features.

Grantees can belong to one or more grantee groups, and they receive entitlements through these group memberships. You can optionally provide a name for display purposes, making it easier to manage your grantees in the dashboard. For example, you might have a user with ID `user_abc123` or a project with ID `project_xyz789`—both would be grantees in Salable.

### Group

A group is a collection of grantees that share access to features from a Subscription. This is how you implement team or organization Subscriptions in Salable. Each group has an owner (usually an organization or team lead) and contains zero or more grantees.

When you create a Subscription, you assign groups to Subscription items to grant access to all the grantees in that group. You can create groups before checkout (useful for pre-onboarding teams) or during the checkout process. A single owner can have multiple groups, which is perfect for organizations with different departments or teams.

Here's what makes groups powerful: once you've created a group for a team or organization, you can reuse that same group for future add-ons and additional Subscriptions. You don't need to recreate the group structure every time—just assign the existing group to new Plans as the team purchases more features.

One more important detail: a single grantee can belong to multiple groups, and they'll gain cumulative access from all their memberships. This makes it easy to handle scenarios like contractors working with multiple clients or employees who belong to cross-functional teams.

### Seat

A seat is essentially a license or slot for a grantee within a per-seat Line Item. The seat count is represented by the quantity on your per-seat Line Item and must be greater than or equal to the number of grantees in the assigned group.

You can define minimum and maximum limits for seats on your Line Item, giving you control over how teams can scale. Seat count and grantee count are managed independently, which means you can have "headroom"—more seats than current grantees—to allow for growth without immediately having to upgrade.

There's an important constraint to be aware of: if a grantee belongs to multiple groups with different Plans that have per-seat pricing, the lowest seat limit across all those Plans applies. This prevents under-provisioning of seats and ensures consistent access.

### Entitlement

An entitlement is a named permission or feature that you can check to control access in your application. Entitlements are named using lowercase snake_case (like `advanced_analytics` or `export_pdf`) and are attached to Plans rather than individual Line Items.

When a Subscription is created with a Plan, the entitlements from that Plan are inherited by the Subscription. To check if someone has access, you use their grantee ID. The pattern works like this: when a grantee is in a group assigned to a Subscription containing a Plan with an entitlement, that grantee has access to that entitlement. It's a chain of relationships that makes access control flexible and powerful.

## Tier Tags and Tier Sets

Tier tags are simply string "tags" belonging to Plans that can be used to **restrict Owners from purchasing one or more Plans that share the same tag**. Plans that share the same the tier tag belong in the same **tier set**, and as such an **Owner can only subscribe to/purchase one Plan in a tier set at a time**. Thus, tier tags and tier sets give you the ability to make your Plans **mutually exclusive purchases**.

What tier tags and tier sets prevent:

- Adding multiple Plans of one tier set to the same cart
- Adding Plans to a cart that belong to the same tier set as a Plan that's already subscribed to by the cart's owner

Note that **owners can still replace a Plan in a Subscription with another Plan belonging to the same Tier Set as they will still only be subscribed to one member of the tier set**.

You can add tier tags to your Plan upon Plan creation or when editing an existing Plan.

---

## Transaction Concepts

### Cart

A cart is a temporary container for Plans that an owner intends to purchase. Think of it as a shopping cart that gets converted into a Subscription after successful checkout. When you add the first item to a cart, you specify a billing interval. You can also optionally provide a currency when creating the cart.

If you provide a currency, Salable cherry-picks Line Items from added Plans that match both the interval and currency combination. If you don't provide a currency, Salable only matches by interval and uses Stripe's geolocation to detect the appropriate currency at checkout.

You can assign grantee groups to cart items before checkout, which is useful for pre-configuring team access. The owner can be updated later—for example, converting a session ID to a user ID after signup. Salable supports multiple active carts per owner, so customers can have different purchasing sessions going simultaneously.

### Cart Item

A cart item represents a single Plan within a cart. Each cart item references a specific Plan and includes a quantity (which matters for per-seat Line Items). It can optionally have a grantee group ID assigned to it.

### Checkout

Checkout converts your cart into a paid Subscription. When you're ready to complete a purchase, you generate a Stripe Checkout session URL that redirects your customer to Stripe's hosted payment page.

You can configure default checkout settings at the Product level, like success and cancel URLs. If you've set these defaults in your Product settings, they'll be used automatically. If you haven't provided Product defaults, you'll need to include any required configuration parameters when generating the checkout link.

Once payment succeeds, Salable creates the Subscription and any necessary grantee groups. At this point, all grantees in the assigned groups immediately gain access to the entitlements attached to their Plans. Checkout works for both authenticated users and anonymous sessions, which is useful for guest checkout flows where you assign the owner ID after the customer signs up.

### Subscription

A Subscription represents an active, recurring billing relationship between an owner and one or more Plans. Created after successful checkout, each Subscription contains one or more Subscription items (which are Plans) and automatically renews based on the billing interval.

Subscriptions aren't static—you can modify them after creation by adding or removing Plans, changing quantities, or updating other settings. When it's time to end a Subscription, you can cancel it either immediately (with proration handling for any unused time) or schedule the cancellation for the end of the current billing period.

### Subscription Item

A Subscription item represents a single Plan within a Subscription. Each item links to the Plan and its Line Items, includes quantities for per-seat pricing, and may have a grantee group assigned to it. When a group is assigned, all grantees in that group receive the entitlements from the Plan. You can individually modify or remove Subscription items without affecting the entire Subscription.

---

## Usage Tracking

### Metered Line Item

Metered Line Items let you charge customers based on what they actually use. Throughout the billing period, you record usage via API calls using a unique slug identifier. At the end of each period, Salable automatically calculates and bills the charges.

Here's what makes meters elegant: you can use the same slug across multiple Plans, keeping your code simple. When recording usage, you just increment against the slug name—like "photo_generation"—regardless of which Plan the user is on. Salable figures out their Plan and bills at the appropriate rate. So one Plan might charge $0.10 per photo while another charges $0.05 per photo, but you're always incrementing the same slug.

When customers change Plans, any outstanding metered usage is invoiced immediately, and new counters start fresh at zero. Plans can have multiple metered Line Items, so you could track photos, videos, and API calls all within the same Plan. Metered Line Items support per-unit, tiered, and volume pricing schemes.

### Meter Slug

A meter slug is the unique identifier used to track usage for metered Line Items. It follows lowercase snake_case format, like `api_calls` or `storage_gb`. When you record usage via the API, you reference this meter slug to increment the counter.

The key advantage is reusability: you can use the same meter slug across multiple Plans. This ensures there's one usage counter per owner per meter slug, preventing double-billing. If you have "photo generation" on both Basic and Pro Plans, use the same meter slug (`photo_generations`) on both. Your code increments one counter, but billing happens at different rates depending on which Plan the customer has.

### Usage Record

A usage record tracks metered usage for an owner during a billing period. When you record usage for the first time in a period, Salable automatically creates a usage record. Throughout the period, this record tracks cumulative usage as you continue to increment the counter.

Usage records move through states during their lifecycle. When usage is actively being tracked during the billing period, the record has `current` status (also referred to as `recorded` status in some contexts). At the end of the billing period (or when a Plan changes), the usage record is finalized and its state changes to `final`. The accumulated usage is then billed. There's one usage record per owner per meter slug per period, keeping things organized and preventing any confusion about what's been billed.

---

## Billing Concepts

### Proration

Proration handles the financial adjustments when Subscriptions change mid-cycle. There are three approaches you can take:

**Charge on Next Invoice** is the most common approach. It refunds any unused time from the old Plan and starts billing for the new Plan at the next cycle. This keeps things clean with minimal immediate financial impact.

**Charge Immediately** refunds the unused time from the old Plan and bills for the new Plan right away, creating an instant invoice. This is useful when you want to settle everything immediately rather than waiting for the next billing cycle.

**No Refund, Charge Next** switches to the new Plan immediately but doesn't refund any unused time. The new Plan starts billing at the next cycle. This essentially gives the customer the benefit of the remaining time on their old Plan while moving to the new one.

### Billing Cycle

The billing cycle is the time period between recurring charges for a Subscription. Its length is determined by the Plan's interval—monthly, yearly, or whatever interval you've configured. The cycle starts on the Subscription creation date (called the billing anchor), and usage for metered items resets at the start of each cycle. All Plans within a Subscription share the same billing cycle.

### Invoice

An invoice is the document showing all charges for a billing period. Salable generates invoices automatically at the end of each cycle, including flat fees, per-seat charges, and metered usage all in one place. You can preview upcoming invoices before the period ends, and once generated, invoices are downloadable as PDFs. Paid invoices are immutable—they can't be changed after payment.

### Billing Anchor

The billing anchor is the date when a Subscription was created, and it determines all future billing dates. This sets the recurring charge date and is used to calculate proration when Subscriptions change. The billing anchor remains consistent across Plan changes. For example, if you create a Subscription on January 15th, it will bill on the 15th of each month going forward.

---

## Operational Concepts

### Cancellation

Cancellation terminates a Subscription, and you have two options for how this happens.

**Immediate cancellation** ends the Subscription right away. Metered usage is finalized and billed, access is revoked immediately, and a final invoice may be generated. This is clean and final.

**End of period cancellation** marks the Subscription for cancellation but lets it continue until the current billing period ends. This can be reversed before the period ends, and there are no immediate access changes—the customer keeps their access until they've used up what they paid for.

### Sync to Latest Price

When you update your pricing, you might want to move existing Subscriptions to the new Prices. That's what syncing to latest Price does. You have a choice: grandfather existing customers by not syncing them (they stay on old pricing), or migrate everyone to the new pricing by syncing them. When you sync, proration rules apply during the transition to handle any mid-cycle adjustments.

### Webhook

Webhooks are HTTP callbacks that Salable sends to your application when events occur. They notify your app of Subscription changes, usage updates, and payment events. Each webhook includes the event type and full payload, and requires signature verification using HMAC to ensure authenticity.

Salable will retry failed webhooks up to 10 times with exponential backoff, and each attempt has a 15-second timeout. Common events include Subscription created, updated, and cancelled; usage recorded and finalized; receipt created; and owner updates.

For a complete guide to configuring webhook destinations, implementing handlers, and monitoring deliveries, see the [Webhooks guide](/docs/webhooks).

---

## Special Patterns

### Anonymous to Authenticated Conversion

This pattern lets you start a cart with a session ID and update it to a user ID after signup. Here's how it works: You create a cart with an owner like `"session_abc123"`, let the user add Plans to their cart, and redirect them to checkout. After payment completes, the user signs up, and you update the owner to their actual user ID like `"user_xyz789"`. This enables guest checkout flows that convert to authenticated accounts seamlessly.

### Pre-Purchase Team Setup

You can add grantees to a group before completing checkout, which offers several benefits. You can invite team members before subscribing, show everyone who will get access, and validate that seat counts match team size. The flow is straightforward: create a grantee group, add grantees to it, create a cart item with the group assigned, set the quantity to match the group size (or more to allow room for growth), and proceed to checkout. Once payment succeeds, everyone in the group immediately has access.

### Cross-Plan Metering

This pattern uses the same meter slug across multiple Plans to maintain a single usage counter. For example, your Basic Plan might charge $0.10 per photo generation using the slug `photo_generations`, while your Pro Plan charges $0.05 per photo generation using the same slug. Usage is counted once in your code—you just increment `photo_generations`—but it's billed at the rate of whichever Plan the customer has. This keeps your implementation simple while giving you pricing flexibility across tiers.

---

## Quick Reference

### Hierarchy Overview

```
Organization
  └─ Product
      └─ Plan (specific interval + currency)
          └─ Line Item (flat/seat/metered/one-time)
              └─ Price (amount in currency)
```

### Access Flow

```
Subscription Item → Assigned Grantee Group → Contains Grantees
                  → Plan → Entitlements → Grantees Have Access
```

### Checkout Flow

```
Cart → Cart Items (Plans + Groups) → Checkout → Payment
  → Subscription Created → Grantee Groups Assigned → Access Granted
```

### Billing Cycle

```
Start Date → Usage Recording → End of Period → Finalize Usage
  → Generate Invoice → Process Payment → New Period Begins
```

---

## Next Steps

Now that you understand the core concepts, explore these guides to implement specific patterns:

- **Getting Started Guide**: Build your first Product and Plan
- **Understanding Entitlements**: Implement feature gating
- **Grantee Groups**: Set up team Subscriptions
- **Webhooks**: Configure real-time event notifications
- **Caching Strategies**: Optimize entitlement checks in production
