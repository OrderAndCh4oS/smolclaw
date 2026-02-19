---
description: Salable gives you complete control over your pricing model. Design products with any combination of flat-rate, per-seat, metered, and Tiered pricing across multiple currencies. This guide walks you through products, plans, and line items so you can set up once and ship immediately.
---

# Products & Pricing

## Overview

**[Products](/docs/core-concepts#product)** and pricing form the foundation of your subscription business in Salable. A Product represents what you're selling—whether that's a SaaS platform, a specific feature set, or an add-on service. Products contain **[Plans](/docs/core-concepts#plan)** that define different pricing Tiers or options, and Plans contain **[Line Items](/docs/core-concepts#line-item)** that determine what customers pay and how they're charged.

This hierarchy enables unlimited payment model configurations. From simple flat-rate subscriptions, per-seat pricing with volume discounts, usage-based metered billing, or any intricate combination your SaaS app needs. Additionally, you can offer the same Product at different prices in different currencies, with different billing intervals, and with different feature access through **[Entitlements](/docs/core-concepts#entitlement)**.

## Understanding the Hierarchy

1. **Product** is the top-level. It represents what you're selling and contains one or more Plans. A Product might be your core SaaS platform, a specific add-on service, or a bundle of features. Products have settings that apply to all Plans within them, like checkout URLs, tax collection preferences, and trial period configurations.

2. **Plan** is what customers purchase. Plans are added to the Cart and checked out as a single unit—customers pay for all Line Items within a Plan together. Plans define which Entitlements customers receive (controlling feature access) and contain one or more Line Items that determine the actual charges.

3. **Line Item** defines a specific charge within a Plan—these are the individual prices that appear on invoices. Line Items are not sold individually; they're bundled together within a Plan. A Plan might have multiple Line Items—for example, a base subscription fee, a per-seat charge, and usage-based billing for API calls. Each Line Item has a type (flat rate, per-seat, or metered), an interval (one-time or recurring), and a billing scheme (per-unit or tiered).

4. **Price** represents the Line Item's pricing at a specific billing interval. A single Line Item can have multiple Prices—one for monthly billing, one for yearly billing, and so on. Each Price contains Currencies for different markets.

5. **Currency** defines the actual pricing in a specific currency. A Price can have multiple Currencies (USD, GBP, EUR), with one marked as the default. This enables global pricing without creating duplicate Line Items.

6. **Tier** (optional) defines pricing breakpoints for tiered billing schemes. Tiers let you charge different amounts based on quantity or usage levels, enabling volume discounts or graduated pricing structures.

## Product Configuration

### Creating a Product

Products can be created on the Salale dashboard and the Salable API.

> **Note** Before creating Products, you must create a Stripe Connect account by setting up a Payment Integration. Products and Plans can be created with minimal Stripe Connect setup. For test mode checkout links, you must complete the business type and personal details forms in Stripe Connect's onboarding. For Live Mode checkout links, you need full onboarding with **Active** status.

Navigate to **Products** in your sidebar. Enter a name for your Product in the Product Name field that clearly describes what you're selling and click Create Product. You should see your new Product in the list below, click the Edit Product button (button with the pencil icon) to continue setting up your Product.

### Product Settings

Product settings define defaults that apply to all Plans within the Product.

- **Checkout URLs**
  Specifies where customers are redirected after completing checkout. The `successUrl` is where they redirected after successful payment, while the `cancelUrl` is where they return if they abandon the checkout process. These URLs can include query parameters to pass information back to your application, allowing you to trigger onboarding flows or analytics tracking based on the checkout result.

- **Allow Promo Codes**
  The **allowPromoCodes** setting enables customers to enter discount codes during checkout. When enabled, a promo code field appears on the Stripe checkout page where customers can apply codes you've configured in your Stripe dashboard.

- **Automatic Tax**
  The **automaticTax** setting enables [Stripe Tax](https://stripe.com/tax) for automatic tax calculation based on customer location. When enabled, Stripe determines the correct tax rate and applies it to invoices. This requires collecting the customer's billing address to determine their tax jurisdiction.

- **Address Collection**
  The **collectBillingAddress** setting determines whether billing address fields are shown at checkout. This is required if you're using automatic tax calculation, as Stripe needs the customer's location to determine applicable tax rates. The **collectShippingAddress** setting adds shipping address fields to the checkout flow if you're selling physical products that require delivery.

- **Card Pre-fill Preference**
  The **cardPrefillPreference** setting determines how payment methods are saved and reused. Set it to `none` to always show an empty payment form, `choice` to let customers decide whether to save their card, or `always` to save payment methods for future purchases.

- **Past Due Entitlements**
  The **pastDueEntitlements** setting controls feature access during payment issues. When set to true, customers retain access to Entitlements even when their Subscription payment fails, and the Subscription enters a past-due state. This maintains access during Stripe's automatic retry period, reducing disruption for customers with temporary payment issues. When set to false, access is immediately revoked when payments fail.

- **Trial Periods**
  The **trialPeriodDays** setting is configured at the Plan level. See [Plan Properties](#plan-properties) for details.

> **Note** Product settings can be overridden at checkout time.

> **Important**: Automatic tax will only work if you have opted in to Stripe Tax in your Stripe account settings. You must enable and configure Stripe Tax in your Stripe Dashboard before using this setting in Salable.

## Plans

Plans represent different pricing tiers, add-ons, or options within a Product. They can be Subscription tiers like Basic, Pro, and Enterprise, or they can represent add-ons and plugins that customers purchase alongside or in addition to a main Plan. Each Plan has different pricing, features, and Line Item configurations.

### Creating Plans

Plans are created within the Product editor in the dashboard. Navigate to the Edit Product page for your Product, scroll to the Plans section, and click **Create Plan**. Enter a nsme for your Plan in the Plan Name field that clearly identifies the tier or option you want your Plan to represent, optionally set a Trial Period in days, and select any Entitlements that customers who purchase this Plan should receive.

The Plan is saved only after you've configured at least one Line Item with pricing.

### Plan Properties

- **Name** identifies the Plan to customers. It is recommended to use clear, descriptive names such as "Professional Plan" or "Enterprise" rather than internal codes. This name appears in checkout flows, invoices, and customer-facing areas.

- **Trial period** gives customers free access for a specified number of days before charging them. Trial periods must be between 1 and 730 days. During the trial, customers have full access to Entitlements but aren't charged until the trial ends. If they cancel during the trial, they won't be charged.

- **Entitlements** define which features customers on this Plan can access. When configuring the Plan, use the Entitlements typeahead input to either search for an existing Entitlement or create a new one inline by typing the Entitlement name and clicking Create. Customers who subscribe receive all selected Entitlements, which you can check in your application to gate features.

- **[Tier Tags](/docs/core-concepts#tier-tags-and-tier-sets)** make Plans mutually exclusive by grouping them into tier sets. When you assign the same tier tag to multiple Plans, an Owner can only subscribe to one of those Plans at a time. To configure tier tags, add them when creating a Plan or when editing an existing Plan. Enter your desired tier tag in the Tier Tag field.

## Line Items

Line Items define the actual charges within a Plan—what customers pay, how often, and how the amount is calculated.

### Naming

Line Item names appear on Stripe invoices, receipts, and checkout pages. Use clear, customer-facing descriptions—"Platform Subscription" rather than "base_fee", "Additional Users" rather than non-descript names such as "per_user".

### Line Item Types

- **Flat Rate** charges a fixed amount per billing cycle, regardless of usage or team size. For example, a \$29/month subscription fee. flat rate Line Items always have a quantity of one.

- **Per Seat** charges based on the number of seats (users, licenses, or units). The price is multiplied by the quantity. For example, \$10 per user per month, where a team with five users pays \$50/month. Per-seat pricing can use simple per-unit billing or tiered pricing with volume discounts. Only one per-seat Line Item is allowed per Plan to avoid ambiguity about seat counting.

- **Metered** charges based on actual usage during the billing period. Customers are billed for what they consume—such as API calls, storage, or processing time. Usage is tracked throughout the billing cycle and invoiced at the end. Metered Line Items require a meter to track usage.

### Interval

Line Items have an interval that determines when they're charged.

- **Recurring** Line Items repeat every billing cycle. The charge appears on every invoice at the configured interval (day, week, month, or year). This is used for Subscription fees, per-seat charges, and recurring metered billing. The interval count proeprty lets you create custom billing periods—for example, an interval of "week" with a count of two creates biweekly billing, or "month" with a count of three creates quarterly billing.

- **One-off** Line Items charge only once, at the start of the Subscription. This is perfect for setup fees, onboarding charges, or one-time purchases.

### Billing Schemes

The billing scheme determines how the Line Item Price is calculated.

- **Per Unit** applies a fixed price per unit. If you set a unit amount of \$10 and the customer purchases five units, they pay \$50. Works for flat Rate, per-seat, and metered Line Items.

- **Flat Rate** (as a billing scheme) charges a single fixed amount regardless of quantity. Typically used when the price type is flat rate with a quantity of one, but can also apply to per-seat items where you want a flat fee regardless of seat count.

- **Tiered** applies different pricing based on quantity or usage levels. Tiers define breakpoints where pricing changes. For example, units 1–10 might cost \$10 each, units 11–50 cost \$8 each, and units 51+ cost \$5 each. Tiered billing supports both volume and graduated modes (explained in the next section).

### Quantity Controls

Line Items have quantity constraints that determine valid purchase amounts.

- **Minimum quantity** sets the minimum amount of units customers must purchase. For flat rate items, this is typically zero or one. For per-seat items, you may want to set a minimum of two to enforce team pricing.

- **Maximum quantity** sets the maximum amount of units customers can purchase. The maximum quantity enforces Plan limits and prevents over-purchase.

- **Default quantity** is the pre-filled amount that customers see when they add the Plan to their Cart. For flat rate items, this is usually one. For per-seat items, you may want to default to a resonable amount (_eg_ five users etc) to give customers a starting point.

- **Allow changing quantities** determines whether customers can adjust the quantity at checkout or when managing their Subscription. Enable this for flexible per-seat pricing, disable it to lock quantities to your configured values.

## Tiered Pricing

Tiered pricing lets you charge different amounts based on quantity or usage levels, enabling volume discounts and encouraging higher-tier purchases.

### Tier Modes

Tiered billing schemes have two modes that determine how prices are calculated across Tiers.

- **Graduated** pricing charges different rates for units within each Tier. Think of it like progressive income tax—the first 100 units cost \$10 each, the next 100 cost \$8 each, and so on. Each unit is priced according to its Tier.

    **Example of Graduated Pricing:**

    ```
    Tier 1: Units 1–100 at $10/unit
    Tier 2: Units 101–500 at $8/unit
    Tier 3: Units 501+ at $5/unit

    Customer purchases 600 units:
    - First 100 units: 100 × $10 = $1,000
    - Next 400 units: 400 × $8 = $3,200
    - Final 100 units: 100 × $5 = $500
    Total: $4,700
    ```

- **Volume** pricing applies a single rate to all units based on the total quantity. When you cross into a new Tier, all units are priced at that Tier's rate, not just the units in that Tier.

    **Example of Volume Pricing:**

    ```
    Tier 1: 1–100 units at $10/unit
    Tier 2: 101–500 units at $8/unit
    Tier 3: 501+ units at $5/unit

    Customer purchases 150 units:
    - All 150 units: 150 × $8 = $1,200
    (All units use the Tier 2 rate of $8)

    Customer purchases 600 units:
    - All 600 units: 600 × $5 = $3,000
    (All units use the Tier 3 rate of $5)
    ```

### Configuring Tiers

Each Tier has three components that define its pricing.

- **Up To** sets the upper limit of the Tier. This is a number representing the last unit in the Tier, or `inf` for the final Tier that has no upper limit. For example, a Tier with "up to 100" includes units 1–100. The Tier after it would start at 101.

- **Unit Amount** is the Price per unit within this Tier. This amount applies to each unit (in graduated mode) or to all units if the total falls in this Tier (in volume mode).

- **Flat Amount** is an optional base fee charged when entering this Tier. This amount is added once if the customer's usage reaches this Tier. For example, you might charge a \$50 flat fee plus \$5 per unit for the top Tier. Flat amounts are often used to cover fixed costs at higher usage levels.

### Tier Configuration Example

Navigate to your Line Item configuration and select **Tiered** as the billing scheme. Choose **Graduated** as the Tier mode. Then configure your Tiers:

Example:

```
Tier 1:
- Up To: 10
- Unit Amount: 10.00
- Flat Amount: 0 (or leave empty)

Tier 2:
- Up To: 50
- Unit Amount: 8.00
- Flat Amount: 0

Tier 3:
- Up To: inf
- Unit Amount: 5.00
- Flat Amount: 0
```

## Prices and Currencies

Prices define how much a Line Item costs at different billing intervals and in different currencies.

### Billing Intervals

A single Line Item can have multiple Prices for different billing intervals. This lets customers choose how often they want to be billed without you creating duplicate Line Items.

Create a Price for each interval you want to support: **Day**, **Week**, **Month**, or **Year**. For example, add a monthly Price at \$29/month and a yearly Price at \$290/year (offering a 17% discount).

### Multi-Currency Support

Each Price can have multiple Currencies, so you can sell globally without duplicating your Product structure.

- **Default currency** is set using the default button on each Currency in the Price form. This is the currency Stripe uses when determining Prices based on geolocation if you omit currency in the Cart. All Line Items in a Product must share the same default currency for geolocation to work correctly.

- **Additional currencies** let you expand into new markets. Add Currencies for each market you want to serve. You can set different Prices in different currencies—Prices don't need to be simple conversions. For example, you might charge \$29/month in USD, £24/month in GBP (not just a conversion), and €27/month in EUR, adjusting for local market conditions and purchasing power.

- **Configuring currencies** in the dashboard is done in the Price configuration. After selecting an interval, click Add Currency and choose from the dropdown. Enter the unit amount and add as many currencies as you need to support.

For tiered pricing, configure Tiers separately for each currency. While Tier breakpoints (the "up to" values) are typically the same across currencies, you might adjust unit amounts and flat amounts for different markets.

### Example Price Configuration

A per-seat Line Item with monthly and yearly billing in multiple currencies:

```
Line Item: User Seats
- Price Type: Per Seat
- Billing Scheme: Per Unit
- Min Quantity: 1
- Max Quantity: 100
- Default Quantity: 5

Monthly Price:
- Interval: Month
- Currency: USD
    - Unit Amount: 10.00
- Currency: GBP
    - Unit Amount: 8.00
- Currency: EUR
    - Unit Amount: 9.00

Yearly Price:
- Interval: Year
- Currency: USD
    - Unit Amount: 100.00
- Currency: GBP
    - Unit Amount: 80.00
- Currency: EUR
    - Unit Amount: 90.00
```

## Combining Multiple Line Items

Plans can include multiple Line Items that work together to create sophisticated pricing models.

### Common Combinations

- **Base fee + Per-seat** is a popular model where customers pay a fixed platform fee plus a per-user charge. For example, \$50/month base fee plus \$10/user/month. This ensures you cover fixed costs while scaling revenue with team size.

- **Flat rate + Metered** combines predictable recurring revenue with usage-based charges. For example, \$99/month base Subscription plus \$0.01 per API call. Customers get a base service level included and pay for additional consumption.

- **Per-seat + Metered** charges for both team size and usage. For example, \$20/user/month plus \$0.50 per transaction processed. This works well when costs scale with both dimensions.

- **Multiple metered items** track different types of usage separately. For example, you might charge \$0.02 per image processed, \$0.01 per API call, and \$0.10 per GB of storage used. Each has its own meter and pricing.

- **One-time setup + Recurring** charges customers once for onboarding or setup, then bills recurring fees. For example, a \$500 setup fee (one-off) plus \$199/month (recurring). The setup fee appears only on the first invoice.

## Troubleshooting

### Cannot Add Per-Seat Line Item

If you're getting an error adding a per-seat Line Item, check if the Plan already has one. If you need different per-seat pricing, use tiered pricing within the single per-seat Line Item rather than creating multiple items.

### Tiered Pricing Validation Errors

Tiers must be configured in ascending order without gaps. Each Tier's starting point is automatically calculated from the previous Tier's "up to" value plus one. The final Tier must have "up to: inf" to handle all quantities beyond the previous Tier.

Unit amounts cannot be negative. If you want to offer discounts at higher Tiers, reduce the unit amount for higher Tiers compared to lower Tiers—don't use negative numbers.

### Currency Amount Format

Salable accepts Prices with or without decimals. You can enter 29 or 29.00 for \$29.00—both are valid.

For zero-decimal currencies (like JPY, KRW), you must enter whole numbers without decimal places. For example, 1000 JPY must be entered as 1000. Entering 1000.00 will cause an error.

### Default Currency Mismatch

If you're using Cart geolocation (omitting currency when creating Carts), all Line Items across all Plans in your Product must share the same default currency. Check each Line Item's default Currency. If Plan A defaults to USD and Plan B defaults to GBP, you must either standardise defaults or require explicit currency selection in Carts.

## Summary

Salable's pricing system lets you build everything from simple flat-rate Subscriptions to complex multi-dimensional pricing with volume discounts and usage-based charges. Use flat rate for fixed charges, per-seat for team-based pricing, and metered for usage-based billing. Support global markets with multi-currency pricing and tiered pricing with graduated or volume modes.

For more on how the Entitlements control feature access, see the [Understanding Entitlements guide](/docs/understanding-entitlements). For managing team access and seats, see [Grantees & Groups](/docs/grantee-groups). For checkout flows and Cart management, see [Cart & Checkout](/docs/cart-and-checkout).
