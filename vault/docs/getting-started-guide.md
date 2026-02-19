---
description: This guide will walk you through everything you need to know to get your subscription billing up and running. In less than 30 minutes, you'll have a complete pricing structure ready to accept payments.
---

# Getting Started with Salable

## What You'll Accomplish

By the end of this guide, you'll have a complete [Subscription](/docs/core-concepts#subscription) and [Entitlement](/docs/core-concepts#entitlement) management system ready and setup within Salable. You'll have a fully configured Stripe Connect account for payment processing, a [Product](/docs/core-concepts#product) with multiple [Plans](/docs/core-concepts#plan), and [Line items](/docs/core-concepts#line-item) with recurring or one-time charges. You'll add items to your [Cart](/docs/core-concepts#cart), create your first test Subscription, configure Entitlements that control feature access, and verify that your subscribed customer has the correct permissions. You'll also have multi-currency support configured, working checkout links, and API keys for integrating with your application.

---

## Step 1: Sign Up and Create Your Organisation

### 1.1 Create Your Account

Navigate to your Salable dashboard and click Sign Up to create an account and complete the authentication process. You'll be prompted to create or join an organisation.

### 1.2 Create Your Organisation

Organisations are how Salable manages multi-tenancy. All your Products, Plans, and Subscriptions are scoped to your organisation.

Enter a name for your organisation in the Name field and complete the organisation setup. You'll be redirected to your dashboard once the setup is complete.

> **Pro Tip** You can manage multiple organisations and switch between them using the organisation switcher in the sidebar.

### 1.3 Understanding Test Mode

You will notice the **[Test Mode](/docs/core-concepts#test-mode-vs-live-mode)** toggle in your sidebar. This allows you to experiment with pricing models safely, create test Subscriptions without real charges, and validate your integration in a test environment before going live. Keep Test Mode **ON** while following this guide.

---

## Step 2: Set Up Your Payment Integration

Before creating a Product, you need to set up a **[Payment Integration](/docs/core-concepts#payment-integration)**—the connection between Salable and Stripe that handles payment processing. This involves creating a [Stripe Connect](https://docs.stripe.com/connect/how-connect-works) account. If you have an existing Stripe account, you can connect it during onboarding.

> **Note** In Test Mode, you won't need to provide all onboarding details (banking, identity verification). However, **business type** and **personal details** are required even for test checkouts.

### 2.1 Create Your Payment Integration

In your dashboard sidebar, click Payment Integrations.

Click the Create Payment Integration button to begin the Stripe Connect onboarding process.

### 2.2 Complete Stripe Connect Onboarding

You will be guided through the Stripe Connect onboarding process step by step. Here you will be asked to enter various business and personal information, including:

- **Business Information**
  Company name, business type, industry, and contact details.

- **Banking Information**
  Bank account details for payouts. Not required in Test Mode.

- **Identity Verification**
  Government-issued ID and business documents. Not required in Test Mode.

> **Important** The **business type** and **personal details** are required for checking out items even while in Test Mode. Without completing these forms, you will not be able to checkout the items we will create later in this guide.

**Review and Submit**
Submit your application. Stripe review typically completes within a few hours but can take up to a few business days.

### 2.3 Verify Integration Status

After onboarding, you'll return to the Payment Integrations page. Your integration status will show as **Active** (complete), **Incomplete**, or **Pending**. You can proceed with creating Products and Plans even if incomplete—full onboarding is only required for Live Mode payments.

> **Note** Account overview components are only available in **Live Mode**. If you're in Test Mode, you'll see a banner prompting you to switch to Live Mode for this step.

---

## Step 3: Create Your First Product

**[Products](/docs/core-concepts#product)** represent what you're selling and contain your Plans and pricing configuration.

### 3.1 Navigate to Products

In your sidebar, click Products to view your Products list.

### 3.2 Create a New Product

There are two ways to create a Product.

**Option A: Simple Form (Recommended)**

Enter the name for your Product in the Product Name field (_eg_ "My SaaS Platform") and click Create Product. Your new Product should appear in the table below.

**Option B: YAML Import (Advanced)**

Download the Product template by clicking Download Template, edit the YAML file with your Product configuration, and upload it using the Import button.

### 3.3 Configure Product Settings

Find your Product in the table and click the Edit button (pencil icon) to open configuration.

### 3.4 Configure Checkout Settings

Click the Settings accordion to expand configuration options.

Set up the checkout experience by configuring the Success URL (where customers go after a successful purchase, like `https://yourapp.com/welcome`) and the Cancel URL (where customers go if they abandon checkout, such as `https://yourapp.com/pricing`).

### 3.5 Additional Options

Configure optional settings based on your needs:

- **Allow Promo Codes at Checkout**:
  Enable this to let customers apply discount codes during checkout. When enabled, a promo code field appears on the Stripe checkout page, allowing customers to enter promotional codes you've configured in your Stripe dashboard.

- **Collect Tax Automatically**:
  Enable this to let Stripe calculate and collect taxes based on customer location. Stripe Tax automatically determines the correct tax rate and applies it to the invoice. This requires collecting the customer's billing address to determine their tax jurisdiction.

    > **Important** This feature requires you to have opted in to Stripe Tax in your Stripe Dashboard. Enable and configure Stripe Tax in your Stripe account settings before using this option.

- **Collect Billing Address**:
  Enable this to display billing address fields during checkout. This is required if you're using automatic tax calculation, as Stripe needs the customer's location to determine applicable tax rates. The billing address also appears on invoices and receipts.

- **Collect Shipping Address**:
  If you're selling physical Products that require shipping, enable this option. It adds shipping address fields to the checkout flow, allowing customers to specify where Products should be delivered. This address is separate from the billing address.

- **Return Entitlements While Past Due**:
  This controls feature access when a customer's payment fails, but their Subscription hasn't been cancelled yet. When enabled, customers maintain access to their Entitlements during the grace period while payment issues are being resolved. When disabled, access is immediately revoked when payments fail.

- **Card Pre-fill Preference**:
  This setting controls how saved payment methods are handled at checkout. Choose None to always show an empty payment form, Choice to let customers select from saved cards or add a new one, or Always to use the customer's default payment method automatically.

### 3.6 Save Product Settings

Click Save to persist your changes.

---

## Step 4: Create Your First Plan

**[Plans](/docs/core-concepts#plan)** define a payment model and the [Entitlements](/docs/core-concepts#entitlement) available to subscribers. You might create Plans for different tiers (_eg_ Basic, Standard, Pro).

### 4.1 Create a Plan

Scroll to the Plans section and enter a name for your Plan in the Plan Name field (_eg_ "Starter Plan"). Click Create Plan and a Plan configuration form will appear.

### 4.2 Configure Plan Settings

Verify or update your Plan name and optionally enter a number of days for the Trial Period to offer a free trial.

### 4.3 Add a Tier Tag

Tier Tags prevent [Owners](/docs/core-concepts#owner) from purchasing multiple Plans that share the same tag—useful for making Plans mutually exclusive. Create a Tier Tag by entering a name in the Tier Tag field.

### 4.4 Add Entitlements

**[Entitlements](/docs/core-concepts#entitlement)** determine which features customers can access based on their Plan. Instead of manually managing feature flags, attach Entitlements to Plans and check them in your application.

In the Entitlements field, use the typeahead to search for existing Entitlements or create new ones. Enter a name (_eg_ `premium_features` or `api_access`) and click Create to add it to your Plan.

---

## Step 5: Add Line Items and Pricing

**[Line Items](/docs/core-concepts#line-item)** are the individual pricing components that make up your Plan's pricing model. A Plan can combine multiple Line Items—for example, a recurring monthly fee plus a one-time setup charge.

### 5.1 Understanding Line Item Types

Salable supports multiple pricing types for Line Items that you can mix and match within a single Plan:

#### Flat Rate

A fixed price charged per billing cycle, regardless of usage or quantity. Perfect for standard Subscription tiers like a \$29/month base Plan. This is the most common pricing model for SaaS applications.

#### Per-Seat

The price is multiplied by the number of seats or users in the Subscription. For example, \$10 per user per month means a team of 5 users pays \$50/month. This model scales naturally with team growth.

#### Metered

Usage-based billing charges are based on actual consumption during the billing period. Examples include \$0.01 per API call, \$0.50 per GB of storage, or \$5 per 1,000 emails sent. Customers only pay for what they use.

#### One-Off

A single charge that doesn't recur, commonly used for setup fees, onboarding charges, or one-off purchases. For example, a \$99 implementation fee is charged once when a customer first subscribes.

### 5.2 Add Your First Line Item

Click Add Line Item to begin. Under Basic Information, enter a descriptive name for the Line Item in the Line Item Name field (_eg_ "Monthly Subscription").

> **Important** Line item names appear on Stripe invoices, so use clear, customer-facing language. Avoid internal codes or technical jargon.

The **Slug** is auto-generated from the Line Item's name and must be unique in your organisation, but you can update it to another value if you prefer. The Slug is used as a pretty identifier for managing quantities in the cart and checkout.

You can optionally add a **Nickname** for internal reference, which won't be shown to customers.

You can optionally enable Allow Changing Quantities to let customers adjust quantities in the checkout.

Select Recurring for the Interval Type if charges should repeat each billing cycle (most common), or One-off for single charges, such as setup fees.

### 5.3 Choose Your Pricing Type

Select the pricing type that matches your billing model:

#### Flat Rate

Select Flat Rate as your pricing type. Optionally configure **Min Quantity** and **Max Quantity** to allow customers to purchase multiple units.

#### Per-Seat

Select Per-Seat as your pricing type, then choose a Billing Scheme:

- **Per Unit**: Multiplies your price by the seat count (_eg_ \$10 × 5 users = \$50/month)
- **Flat Rate**: Charges a fixed total regardless of seat count
- **Tiered**: Applies volume discounts or graduated pricing based on seat count

Configure **Min Quantity** and **Max Quantity** to set the allowed seat range. This helps differentiate pricing tiers—your Basic Plan might cap at 10 seats, while Pro requires a minimum of 11.

> **Important** Each Plan can only have one Per-Seat Line Item.

#### Metered

Select Metered as your pricing type, then choose a Billing Scheme:

- **Per Unit**: Multiplies your rate by actual usage (_eg_ \$0.01 × 1,000 API calls = \$10)
- **Tiered**: Applies volume or graduated pricing based on usage totals

Use the Select Meter typeahead to choose an existing meter or create a new one. Meters track usage and prevent double-billing.

#### Tiered Pricing (Per-Seat and Metered)

If you selected Tiered billing, choose a Tier Mode:

- **Volume**: All units charged at the rate of whichever tier the total falls into. Example: 0–10 units cost \$10 each, 11+ cost \$8 each. At 15 units, all 15 are charged at \$8 = \$120.

- **Graduated**: Different rates apply to each tier separately. Example: first 10 units at \$10 each, next 10 at \$8 each. At 15 units: (10 × \$10) + (5 × \$8) = \$140.

### 5.4 Configure Prices and Currencies

Configure prices for each billing interval (monthly, yearly) and currency (USD, GBP, EUR) you want to support.

#### Add a Price Interval

In your Line Item, click Add Price and select a Billing Interval from Day, Week, Month (most common), or Year.

> **Pro Tip** You can add multiple intervals. For example, offer both monthly (\$29) and yearly (\$290 – 17% discount) options.

#### Add Currency Options

For each interval, you can support multiple currencies. Click Add Currency and select a Currency from the dropdown (_eg_ USD, GBP, EUR etc). Enter the pricing based on your billing scheme.

#### For Per-Unit or Flat-Rate:

Enter the Unit Amount as the price (for example, 29 or 29.00 for \$29.00).

> **Note** Some currencies do not support decimal values and entering a decimal value may cause an error. For zero-decimal currencies such as JPY or KRW, only whole numbers are allowed (_eg_ 1000 for 1000 JPY).

#### For Tiered Pricing:

Configure each tier by setting the First Unit (auto-calculated from the previous Tier), entering the Last Unit as the upper limit (or "inf" for the final tier), and specifying the Unit Amount as the price per unit in this Tier. You can optionally add a Flat Amount as a base fee for reaching this Tier. Click Add Tier to add more Tiers.

**Example Tiered Pricing:**

```
Tier 1: Units 1–10     → $10/unit + $0 flat
Tier 2: Units 11–50    → $8/unit + $0 flat
Tier 3: Units 51–inf   → $5/unit + $0 flat
```

Repeat for each currency you want to support. Stripe can auto-detect customer location and display the appropriate currency at checkout.

### 5.5 Add More Line Items (Optional)

Click Add Line Item to add additional charges. Common scenarios: base fee plus per-seat charges, monthly fee plus metered usage, or one-time setup fee plus recurring Subscription.

---

## Step 6: Save and Review Your Plan

### 6.1 Review Your Configuration

Before saving, verify your configuration is complete:

- **Plan Name**: Use customer-facing names (appears on checkout and invoices)
- **Line Items**: Correct pricing types configured with appropriate quantities
- **Pricing Intervals**: All billing intervals have prices configured
- **Currency Support**: All target currencies have prices for each interval
- **Tier Structures**: Breakpoints are logical, final tier ends with "inf"

### 6.2 Save the Plan

Click the Save Plan button. Your Plan is now ready to accept Subscriptions.

### 6.3 Create Additional Plans (Optional)

To offer multiple tiers, repeat steps 4–6 with different configurations (_eg_ Starter at \$29/month flat rate, Professional at \$99/month per-seat, Enterprise with custom tiered pricing).

---

## Step 7: Test Your First Checkout

> **Important** Test checkouts require the **business type** and **personal details** forms completed in Stripe Connect. Full onboarding is only needed for Live Mode.

### 7.1 Add Your Plan to Cart

At the bottom of your Plan, you'll find the Add to Cart form:

- **Currency**: Select from your configured currencies
- **Interval**: Choose the billing frequency (Month, Year, etc.)
- **[Owner](/docs/core-concepts#owner)** (required): An ID in your system for looking up Subscriptions—typically an organisation, team, or user ID
- **[Grantee](/docs/core-concepts#grantee)** (optional): The entity receiving feature access—typically a user ID. Can be assigned later for anonymous checkouts.

Click Add to Cart to add the Plan to your **[Cart](/docs/core-concepts#cart)**.

### 7.2 View Your Cart

Click Go to Cart to view your Cart. You can review the Plan, interval, currency, quantity, and price.

### 7.3 Complete Test Checkout

Click Checkout Cart to be redirected to Stripe's checkout page. Use [Stripe's test cards](https://docs.stripe.com/testing) (_eg_ `4242 4242 4242 4242`, any future expiry, any 3-digit CVC). Complete checkout and you'll be redirected to your Success URL.

You've created your first test Subscription.

---

## Step 8: View Your Subscription

### 8.1 Navigate to Subscriptions

In your sidebar, click Subscriptions to see your newly created test Subscription.

### 8.2 Explore Subscription Details

Click on the Subscription to view:

- **Status**: Active, trialling, past_due, cancelled, etc.
- **Plans Included**: All Plans attached to this Subscription
- **Line Items and Pricing**: Breakdown of all charges
- **Entitlements Granted**: Feature access permissions
- **Billing Cycle**: Current period, next renewal date
- **Payment History**: Past invoices and records

### 8.3 Test Subscription Management

Try these management actions:

- **Update Quantities**: Adjust seat count to see proration in action
- **Add Additional Plans**: Simulate purchasing add-ons
- **View Upcoming Invoice**: Preview the next charge
- **Cancel Subscription**: Test cancel at period end vs immediate cancellation

### 8.4 Check Entitlements

Verify the subscribed user has access to the Entitlements you configured.

**Via the Dashboard**

Navigate to Entitlement Check in your sidebar. Enter the Grantee ID and click Check Grantee to see all Entitlements your Grantee has access to.

**Via the API**

```bash
curl "https://api.salable.app/api/entitlements/check?granteeId=user_123" \
  -H "Authorization: Bearer YOUR_PUBLISHABLE_KEY"
```

The response includes an array of Entitlements. Check whether the specific Entitlement you need is in the array before granting access to that feature.

---

## Step 9: Get Your API Keys

In your sidebar, click API Keys. You'll see two types:

- **Publishable Key**: Safe to use in frontend code
- **Secret Key**: Must be kept secure on your backend

Click the copy button and store them securely (_eg_ in your `.env`). Test Mode and Live Mode have separate keys.

> **Warning** Never expose your Secret Key publicly.

---

## Common Questions

### Can I change pricing for existing Subscriptions?

You can update prices and sync existing Subscriptions to new prices, or grandfather existing customers on old pricing. Use the **Sync Subscriptions** feature in the Product editor.

### How do I handle Plan upgrades and downgrades?

Salable handles this with [proration options](/docs/core-concepts#proration):

- **Charge on next invoice**: Prorated adjustment on next billing cycle
- **Charge immediately**: Instant invoice with prorated amounts
- **No refund, charge next**: Switch immediately, new charges start next cycle

### Can customers purchase multiple Plans at once?

Customers can add multiple Plans to their cart and checkout in a single transaction—useful for base Product plus add-ons.

> **Note** Each Plan can only be added to the cart once.

---

## Summary

You now have a connected Stripe account, a Product with Plans and Line Items, a working checkout flow, API keys, and your first test Subscription. Your billing infrastructure is ready.
