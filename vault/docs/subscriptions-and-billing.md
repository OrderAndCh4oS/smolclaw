---
description: 'Salable manages the full subscription lifecycle, ensuring entitlements stay in sync as customers upgrade, downgrade, or cancel. This guide walks you through how subscriptions work and the control you have from checkout to cancellation.'
---

# Subscriptions & Billing

## Understanding Subscriptions

### How Subscriptions Are Created

Subscriptions are created when a customer completes checkout. Stripe notifies Salable of the successful payment, and Salable creates a Subscription from the Plans purchased in the [Cart](/docs/core-concepts#cart).

The Subscription inherits properties from the Cart—currency, billing interval, Grantee Group assignments, and any metadata—and belongs to the [Owner](/docs/core-concepts#owner) who made the purchase. If the Cart included Grantee Group assignments, these Groups are automatically linked to the appropriate [Subscription Items](/docs/core-concepts#subscription-item), giving team members immediate access to [Entitlements](/docs/core-concepts#entitlement).

### Subscription Status

Subscriptions move through several states during their lifecycle:

- **active**: in good standing with successful payments; full Entitlement access
- **past_due**: payment failed; Stripe is retrying via [Smart Retries](https://stripe.com/blog/how-we-built-it-smart-retries). You can configure whether customers retain Entitlement access during this period
- **cancelled**: terminated and will not renew. Immediate cancellation revokes access right away; end-of-period cancellation maintains access until the billing cycle ends
- **trialling**: trial period with full access but no charge yet. Transitions to active when the trial ends, unless cancelled
- **incomplete**: initial payment failed. Stripe retries briefly before moving to cancelled

### Subscription Items

Subscriptions contain [Subscription Items](/docs/core-concepts#subscription-item), one for each Plan purchased. A customer buying your main Product plus add-ons will have multiple Subscription Items tracked separately.

Within each Subscription Item, individual Line Items maintain their own quantities. A per-seat Line Item tracks purchased seats, a consultancy Line Item might track purchased hours, and a metered Line Item tracks usage records.

Subscription Items inherit Entitlements from their Plan and can be associated with Grantee Groups. If a customer assigned a team Plan to a Grantee Group during checkout, that association persists, ensuring all group members receive the appropriate Entitlements.

## Managing Subscription Items

You can add, remove, or replace Plans on a Subscription in a single request. When making changes, you specify the proration behaviour to control how billing is handled. All actions in the request are processed together to calculate a single billing adjustment. Plans must match the Subscription's currency and billing interval.

- **Add** adds a new Plan to the Subscription.
- **Remove** removes an existing Plan from the Subscription. You cannot remove the last one.
- **Replace** swaps one Plan for another. Useful for upgrades or downgrades.

### Tier Tags

If your Plans use [Tier Tags](/docs/core-concepts#tier-tags-and-tier-sets), you can replace one Plan with another from the same tier set. For example, if a customer is on the "Basic" Plan, it can be replaced with the "Pro" Plan even if they share the same tier tag. This is how to handle upgrades/downgrades within a tier set.

You cannot add a Plan that shares a tier tag with a Plan already on the Subscription. If you need to move a customer to a different Plan within the same tier set, use the replace action rather than adding the new Plan separately.

## Quantity Management

After a customer purchases a Subscription, you can adjust the quantity of each Line Item on their Plan. When making a change, you specify the proration behaviour to control how billing is handled. The minimum and maximum limits configured on the Line Item are enforced.

For per-seat Line Items, the quantity determines how many seats are available for the associated Grantee Group. You can increase the quantity at any time to add seats, but you cannot decrease it below the current number of group members. You must remove members from the group first.

## Proration

Proration ensures fair billing when Subscriptions change mid-cycle. When a customer upgrades, downgrades, adds Plans, or changes quantities between billing dates, the amount owed for the partial period is prorated based on the time remaining until the next billing anchor.

For example, if a customer with a \$100/month Plan upgrades to a \$150/month Plan on day 10 of a 30-day cycle, the prorated charge is approximately \$33.33 (the \$50 difference × 20/30 remaining days). At the next billing date, the full \$150 is charged. This applies equally to seat additions, plan changes, and add-ons—all changes synchronise to the single billing anchor, so customers receive one invoice per period.

### Proration Behaviours

Salable provides the following proration behaviours:

- **create_prorations** immediately calculates the difference between the old and new Subscription value and generates an invoice or credit right away. If a customer upgrades from a \$50/month Plan to a \$100/month Plan halfway through the month, they're immediately charged approximately \$25 (the prorated difference for the remaining half-month). At their next regular billing date, they'll be charged the full \$100 for the upcoming month.

- **always_invoice** creates an invoice immediately for any proration amount, even if the change results in a credit. This ensures you're always generating invoices for audit purposes, though credits still apply to the customer's balance for future billing.

- **none** turns off proration entirely. If you upgrade a Plan with this setting, the customer continues paying the old rate until their next billing date, at which point they start paying the new rate. This is simpler for customers to understand and avoids mid-cycle charges, but it means you may be giving away upgraded access for free during the transition period. This works well for downgrades when you want to be generous and let customers keep premium features until the end of their paid period.

### Choosing the Right Proration Strategy

The proration behaviour you specify depends on the nature of the update. Here are a few strategies:

- Upgrades: **create_prorations** is typically the right choice. Customers understand they're paying more for better features, and immediate billing ensures you're compensated for the value you're providing.
- Downgrades: **none** can be generous—customers keep premium features until the end of their paid period before switching to the lower price.
- Add-ons: **create_prorations** is a sensible option because they're actively asking for a feature and expect to pay for it. The immediate charge confirms they have access right away.
- Complex modifications (_eg_ multiple updates): **create_prorations** calculates the net difference, potentially resulting in a small charge, a small credit, or nearly zero change.

## Cancellation Management

### End-of-Period Cancellation

Schedule a Subscription to cancel at the end of the current billing period by disabling auto-renewal. The Subscription remains active until the end of the period, then terminates without renewal. No refund is issued—the customer receives the full value of what they paid.

After scheduling, the Subscription includes `cancelAtPeriodEnd: true`. Use this to show customers when access ends. To reverse a scheduled cancellation, re-enable auto-renew.

### Immediate Cancellation

Immediate cancellation terminates the Subscription and revokes Entitlements. A prorated refund is issued for the unused portion of the billing period.

Use immediate cancellation for terms of service violations, account deletions, or when switching billing intervals.

## Billing Cycles and Intervals

### How Billing Anchors Work

Every Subscription has a billing anchor date—the day of the month when the Subscription renews and the next billing period begins. This anchor is set when the Subscription is first created, based on the date the customer completed checkout.

If a customer subscribes on January 15th with monthly billing, their anchor is the 15th. They'll be billed on the 15th of each month for the upcoming period.

This anchor-based billing provides customers with consistency—they know precisely when charges will occur each month. For annual Subscriptions, the anchor works the same way, spanning years instead of months.

### Month-End Edge Cases

Billing anchors on the 29th, 30th, or 31st of the month present special challenges due to varying month lengths.

Stripe and Salable handle this by billing on the last available day of shorter months. A January 31st anchor bills on February 28th (or 29th in leap years), then March 31st, April 30th, May 31st, and so on. The anchor remains conceptually tied to the 31st, but actual billing happens on the last available day of each month.

This behaviour ensures customers never miss a billing date while keeping the cycle as close to monthly as possible. However, it does mean billing periods vary slightly in length—a billing period ending on February 28th is shorter than one ending on March 31st.

## Invoice Management

Stripe generates an invoice for every Subscription billing event. Each invoice includes Line Items showing what was billed, payment status, total amount, and an `invoicePdf` URL for downloadable PDF receipts.

For metered Line Items, invoices show usage charges with quantity consumed, per-unit price, and total (_eg_ "API Calls: 1,450 × \$0.10 = \$145.00").

You can also preview what customers will be charged on their next billing date before it's finalised. The preview includes recurring charges, pending metered usage, account credits, and the final amount.

## Price Synchronisation

### Understanding Price Changes

When you update a price in Salable, existing Subscriptions continue billing at the old price by default—existing customers are "grandfathered" into price updates.

> **Note** You can configure the billing model to apply updated prices to all customers.

### Syncing to New Prices

Use the Price Synchronisation endpoint to migrate a Subscription to the latest pricing. This updates the Subscription Items to reference the current prices for their Plans, applying your new pricing to existing customers.

The proration behaviour determines when the new pricing takes effect. Using `none` means the Subscription continues at the old price through the current billing period, then switches to the new price at the next renewal. Using `create_prorations` means the price change takes effect immediately with appropriate prorated charges or credits.

### Communicating Price Changes

Best practices for price changes:

- Announce updates at least 30 days in advance
- Explain the reasons for the price update and any value changes
- Clearly state the dates when the change takes effect for existing customers
- Consider offering options to lock in current pricing

Using end-of-period price synchronisation respects the customer's current billing cycle while giving them time to adjust.

> **Important** Price notification requirements vary by jurisdiction—some require 30 days' notice, others 60 days or more. Research legal requirements for your customer locations or consult legal counsel before implementing price changes.

## Payment Failures and Dunning

### Understanding Past Due Status

If a scheduled Subscription payment fails, the Subscription enters a `past_due` state. Stripe automatically attempts [Smart Retries](https://docs.stripe.com/billing/revenue-recovery/smart-retries), adapting the retry schedule based on failure reason and historical patterns.

During this period, you can control whether customers retain Entitlement access. Maintaining access can reduce frustration if the failure is temporary, but it means providing service without current payment. The right choice depends on your risk tolerance.

### 3D Secure and Strong Customer Authentication

In the European Economic Area, Strong Customer Authentication (SCA) regulations require additional verification for certain transactions. This is commonly implemented through 3D Secure (3DS). While recurring Subscription payments benefit from exemptions, several scenarios trigger authentication:

- **Price increases** beyond certain thresholds (often 30 EUR or equivalent)
- **Initial Subscription payments** (handled automatically by Stripe checkout)
- **Payment method changes**
- **Large mid-cycle charges** from upgrades or expensive add-ons

When a payment fails due to SCA, the customer must actively authenticate. Updating their card won't resolve the issue. Notify customers that verification is required for security purposes, and provide Stripe's billing portal to complete the authentication challenge.

For price increases or mid-cycle modifications that may trigger authentication, communicate proactively. Mention that their bank may require verification, and consider offering the option to delay changes until the next billing date to avoid mid-cycle triggers.

> **Note** SCA requirements are mandatory in the European Economic Area. Other regions may have different requirements or none at all. Consider your customer distribution when planning communication strategies.

### Customer Communication During Dunning

While Stripe handles payment retries, you are responsible for customer communication. If a payment fails, proactively notify the customer through email or in-app messages. Explain the failed payment, provide a link to update their payment method, and reassure them about how much time they have before access is affected.

If retries continue to fail, escalate urgency. After several days, make it clear that cancellation is imminent.

If a payment succeeds after a retry, confirm the charge was successful so customers know the issue is resolved.

### Providing Payment Update Links

The easiest way for customers to update their payment method is through Stripe's hosted billing portal. You can generate portal links that take customers directly to a secure page where they can update cards, view billing history, and manage their Subscription. Include these portal links prominently in your communications about payment failures.
