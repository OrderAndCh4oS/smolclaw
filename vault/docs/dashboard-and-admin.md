---
description: 'The dashboard is your control centre for configuring products, managing subscriptions, and handling customers. This guide walks through each section and how to use it.'
---

# Dashboard & Admin

## Overview

The Salable dashboard is your command center for managing subscription infrastructure without writing code. While the API provides programmatic access for your application, the dashboard gives you and your team a visual interface for configuring products, monitoring subscription health, responding to customer support requests, and understanding your revenue patterns.

The dashboard is designed around two key principles: you should be able to configure complex pricing models visually, and you should have immediate visibility into subscription status and customer issues. Whether you're setting up your first product, debugging a customer's payment problem, or analyzing which plans drive the most revenue, the dashboard provides the tools you need.

This guide walks you through the major areas of the dashboard, explaining not just what each section does but when and why you'd use it. Understanding these workflows helps you operate your subscription business efficiently and respond quickly to customer needs.

## Organization Management

Organizations are the top-level container for everything in Salable. All your products, plans, subscriptions, and settings are scoped to an organization. Understanding organization management is essential whether you're working solo or coordinating with a team.

### Creating and Switching Organizations

When you first sign up for Salable, you create or join an organization. Your account can belong to multiple organizations, which is useful if you manage several businesses or work with clients who each have their own Salable account.

The organization switcher appears in the dashboard sidebar, showing your current organization and providing access to others you belong to. Switching organizations is instantaneous—the entire dashboard updates to show the selected organization's data, settings, and resources.

This organizational separation ensures complete data isolation. You can't accidentally modify one business's products while viewing another's subscriptions. Each organization has its own API keys, Stripe connection, products, and customer base.

### Organization Settings

Organization settings control fundamental aspects of how your account operates. Access these settings through the sidebar to manage:

**Organization Name**
Configure your organization's name, which appears throughout the dashboard and in some customer-facing contexts. Choose a name that clearly identifies your business to avoid confusion when switching between multiple organizations.

**Team Management**
View and manage team members who can access your organization's data and settings.

**API Keys**
Access your API keys for both test and live modes, which your application uses to integrate with Salable.

**Webhook Endpoints**
Configure webhook endpoints where Salable sends real-time event notifications about subscription changes.

**Stripe Integration**
Manage your Stripe connection for processing payments in live mode.

### Team Management

Organizations support multiple team members with different roles and permissions. This collaboration structure lets your whole team access the tools they need without sharing personal login credentials.

Invite team members by entering their email address in the team management section. They receive an invitation email with a link to join your organization. If they don't already have a Salable account, they'll create one as part of accepting the invitation.

Team members can view and modify products and plans, access subscription data, manage customer support issues, and configure organization settings based on their permissions. This shared access streamlines operations—your customer support team can investigate subscription issues while your product team configures new pricing tiers, all without coordinating access to a single account.

When team members leave your organization, remove them from the team to revoke their access immediately. This ensures that former employees or contractors can no longer view customer data or modify your configuration.

## Test Mode and Live Mode

The dashboard operates in two distinct modes that mirror the API's test and live environments. Understanding how to use these modes effectively is crucial for safe development and reliable operations.

### Understanding Mode Separation

Test mode and live mode maintain completely separate data. Products created in test mode don't appear in live mode and vice versa. Subscriptions, customers, usage records, and all other data are similarly isolated.

This separation creates a safe sandbox where you can experiment with pricing models, test integration flows, and validate changes without affecting real customers or processing actual payments. Once you've thoroughly tested changes in test mode, you can replicate them in live mode with confidence.

The mode toggle appears prominently in the dashboard sidebar. The current mode is always visible, and switching modes is a single click. The entire dashboard updates to show the appropriate environment's data.

A visual indicator—typically a colored banner or badge—reminds you which mode you're in at all times. This prevents accidentally modifying production data when you intended to work in test mode, or wondering why changes aren't affecting real customers when you're viewing test data.

### Working in Test Mode

Use test mode extensively during initial setup, development, and when planning changes to your pricing structure:

**Product Configuration**
Create products and plans that mirror your intended live mode structure. This ensures your tests accurately represent production behavior.

**Checkout Testing**
Test the complete checkout flow using Stripe's test cards. Verify that payments process correctly and customers are redirected appropriately.

**Subscription Verification**
Create subscriptions and verify entitlement access works as expected. Check that grantees receive the correct permissions based on their subscription.

**Modification Testing**
Experiment with subscription modifications and cancellations. Test upgrades, downgrades, quantity changes, and the various proration options.

**Webhook Integration**
Test webhook delivery and your application's event handling. Ensure your application responds correctly to subscription events.

Test mode connects to Stripe's test environment, which accepts special test card numbers documented in Stripe's documentation. These test cards let you simulate successful payments, failed payments, authentication requirements, and various other scenarios without moving real money.

Changes you make in test mode never affect your live customers. This freedom to experiment is invaluable—you can try different pricing structures, test edge cases, and refine your subscription flows without any risk to your production environment.

### Transitioning to Live Mode

Once you've thoroughly tested your setup and integrated your application with the test mode API, you're ready to transition to live mode. This transition involves several steps that ensure a smooth launch.

First, switch to live mode in the dashboard. You'll notice that your product catalog is empty—remember, test and live mode data are completely separate. Recreate your products and plans in live mode, matching the structure you finalized in test mode. This manual recreation ensures you're intentional about what goes into production and gives you a chance to make any last-minute adjustments.

Update your application to use live mode API keys instead of test keys. This typically means changing environment variables or secrets management configuration. Verify that your application is pointing to live mode endpoints and handling live mode webhooks correctly.

Complete the Stripe onboarding process for your live mode organization. While test mode doesn't require full Stripe setup, live mode requires completed onboarding before you can process real payments. Follow the Stripe Connect flow accessible from the dashboard to provide your business information, banking details, and identity verification.

Test your first real subscription using a small amount or a test purchase by a team member before announcing to customers. This final verification ensures everything is wired correctly and working as expected in the production environment.

### Maintaining Both Environments

Even after launching in live mode, maintain your test mode environment as a staging area for future changes. When planning new features, pricing updates, or integration changes, prototype them in test mode first. This ongoing use of test mode as a development environment prevents production issues and maintains the safety of your experimentation space.

## Product and Plan Management

The product and plan configuration interface is where your pricing strategy takes shape. This visual editor lets you create complex pricing structures without writing code, though the underlying configuration is also available in YAML format for those who prefer infrastructure-as-code approaches.

### Product Creation

Access the products section from the dashboard sidebar to view your product catalog. In test mode, this starts empty. In live mode, it shows your active products and any archived products you've deprecated.

Creating a product begins with the **Create Product** button. The simplest flow involves entering a product name and clicking create—the product appears in your catalog immediately with default settings.

The product name should be clear and descriptive. This name appears in the dashboard, in API responses, and potentially in customer-facing areas depending on your integration. Choose names like "SaaS Platform" or "Analytics Add-on" rather than internal codes or abbreviations.

Once created, click the product to open the detailed configuration editor. This is where you define plans, configure settings, and build out your complete pricing structure.

### Product Settings Configuration

The product settings panel controls behavior that applies to all plans within the product. These settings provide sensible defaults for checkout and billing behavior while allowing per-checkout overrides through the API when needed.

**Checkout URLs** define where customers are redirected after the payment process. The success URL is where they land after successfully subscribing—typically your application's welcome page, onboarding flow, or dashboard. The cancel URL is where they return if they abandon checkout before completing payment—often your pricing page so they can reconsider their options.

These URLs can include query parameters to pass information back to your application. For example, `https://yourapp.com/welcome?plan=pro` lets your application know which plan the customer selected, even though the subscription information also arrives via webhook.

**Payment Collection Settings**

Control various aspects of the checkout experience:

- **Promotional Codes**: Enable to add a field where customers can enter discount codes you've created in Stripe
- **Automatic Tax**: Enable Stripe Tax for jurisdiction-appropriate tax calculation without manual configuration (requires opting in to Stripe Tax in your Stripe Dashboard)
- **Billing Address Collection**: Display billing address fields during checkout—required for tax calculation and useful for invoicing
- **Shipping Address Collection**: Display shipping address fields during checkout—useful if you're selling physical goods that require delivery

**Card Storage Preferences**

Determine how payment methods are saved for future use:

- **None**: Don't save payment methods. Customers must enter payment details for each purchase
- **Choice**: Let customers decide whether to save their card during checkout
- **Always**: Automatically save payment methods for streamlined future payments and subscription renewals

**Entitlement Access During Payment Issues**

The past due entitlements setting controls feature access when payments fail:

- **Enabled**: Customers retain access to their entitlements while Stripe attempts payment retry. This minimizes disruption for customers with temporary payment issues
- **Disabled**: Entitlements are immediately revoked when payment fails. This prevents providing service without current payment

The right choice depends on your business model and tolerance for providing service without guaranteed payment.

### Creating and Configuring Plans

Plans represent pricing tiers, add-ons, or options within a product. They can be subscription tiers or add-ons and plugins that customers purchase alongside a main plan. The plans section of the product editor shows existing plans and provides access to create new ones.

Click **Create Plan** to open the plan configuration interface. This guided flow walks you through the essential elements: plan name, trial period, tier tags, entitlements, and line items.

The plan name identifies the tier to customers. Use clear, marketing-friendly names like "Professional" or "Enterprise" rather than codes. This name appears in checkouts, invoices, and your customer portal.

Trial periods give customers free access for a specified number of days before charging them. Enter the number of days (between 1 and 730) or leave it blank for no trial. During trials, customers have full access to entitlements but aren't charged. If they cancel before the trial ends, they're never billed.

[Tier Tags](/docs/core-concepts#tier-tags-and-tier-sets) make plans mutually exclusive by grouping them into tier sets. When you assign the same tier tag to multiple plans, an owner can only subscribe to one of those plans at a time. This is useful for subscription tiers where customers should choose one option (Basic, Pro, or Enterprise) rather than subscribing to multiple. Enter the tier tag string in the Tier Tag field, plans that share the same value belong to the same tier set.

Entitlement selection determines which features customers on this plan can access. The typeahead input lets you search for existing entitlements or create new ones inline. Simply type the entitlement name and click **Create** if it doesn't exist yet. The entitlement naming convention is lowercase with underscores, like `advanced_analytics` or `unlimited_exports`.

### Line Item Configuration

Line items define the actual charges within a plan. This is where pricing structure becomes concrete—flat fees, per-seat charges, usage-based billing, or combinations of these models.

Click **Add Line Item** to open the line item editor. Start by selecting the line item type: flat rate for fixed recurring fees, per-seat for team-based pricing, metered for usage-based billing, or one-time for setup fees and single charges.

**For flat rate line items**, configure the billing interval (monthly, yearly, or custom intervals), the price in each currency you support, and optionally any tiered pricing if you want volume-based discounts even for flat fees.

**For per-seat line items**, you have additional configuration options. The min seats setting enforces a minimum purchase quantity—useful for team plans where you want at least 5 seats per subscription. The max seats setting caps the maximum quantity, which can help you identify when customers might need enterprise agreements. Variable seating allows customers to choose their quantity within these bounds, while fixed seating sells plans with a predetermined number of seats.

Tiered per-seat pricing lets you offer volume discounts. Configure tiers with breakpoints like 1–10 seats at $10 each, 11–50 seats at $8 each, and 51+ seats at $6 each. Customers automatically get the appropriate tier pricing based on their quantity.

**For metered line items**, configure the slug that uniquely identifies this usage type, the price per unit of usage, and the aggregation method. The slug is critical—it's what you provide when recording usage through the API, and it must be unique across your organization. Use descriptive slugs like `api-calls` or `storage-gb` rather than generic names.

Each line item can have prices for multiple billing intervals and currencies. The editor shows tabs or sections for monthly, yearly, and custom intervals. Within each interval, specify prices in multiple currencies with one marked as default.

### YAML Import and Export

For teams who prefer infrastructure-as-code approaches or need to replicate products across environments, the dashboard supports YAML import and export.

Click **Export to YAML** on any product to download a complete configuration file including all plans, line items, prices, and settings. This YAML file is version-controllable, shareable with team members for review, and serves as documentation of your pricing structure.

The **Import from YAML** feature lets you upload a configuration file to create or update products. This is particularly useful when transitioning from test mode to live mode—export your tested configuration, review it, and import it into live mode rather than manually recreating everything.

YAML import validates the configuration before applying changes, catching errors like missing required fields, invalid price configurations, or reference to non-existent entitlements. If validation fails, error messages indicate what needs to be fixed.

### Managing Entitlements

The entitlements section, accessible from the sidebar, shows all entitlements across your organization. This global view helps you understand your complete feature access structure and manage entitlements that might be shared across multiple products and plans.

Create standalone entitlements here if you prefer to define your entitlement structure before building products, or manage entitlements that were created inline during plan configuration.

Each entitlement has a name (the slug used in API checks), a description for team reference, and optionally an expiry date if the entitlement should automatically revoke after a certain date. The interface shows which plans include each entitlement, making it easy to audit feature access across your pricing tiers.

Archive entitlements you no longer use rather than deleting them. Archived entitlements don't appear in plan configuration interfaces but remain in the system so historical data remains consistent. If subscriptions still reference an archived entitlement, those customers retain access until their subscription changes.

## Subscription Management

The subscriptions section gives you operational visibility into your customer base. This is where you monitor subscription health, investigate customer issues, and make administrative changes when needed.

### Subscription List and Filtering

The subscriptions list shows all subscriptions in the current mode, with powerful filtering and search capabilities to help you find relevant subscriptions quickly.

The default view shows active subscriptions sorted by creation date, but you can customize this view extensively. Filter by status (active, past_due, canceled, trialing) to focus on specific subscription states. Search by customer email or owner ID to find a specific customer's subscriptions. Filter by product or plan to see all customers on a particular tier. Sort by various fields like creation date, next billing date, or subscription value.

These filters combine, so you can answer questions like "show me all past_due subscriptions for the Pro plan" or "find all subscriptions created in the last week." This flexibility is essential for support operations and revenue analysis.

Each subscription in the list shows key information at a glance: the customer's email or owner ID, current status, subscription plans, and the next billing date. Click any subscription to open the detailed view.

### Subscription Detail View

The subscription detail page provides comprehensive information about a single subscription and tools for making modifications or resolving issues.

The summary section shows the customer information including owner ID and contact details if available, current subscription status and any scheduled changes (like upcoming cancellation), creation date and subscription age, and the next billing date and amount.

The subscription items section lists all plans included in the subscription. For each item, you see the plan name and details, quantity (for per-seat plans), associated grantee group if applicable, and the price being charged per interval.

The billing history section shows all invoices for this subscription. Each invoice entry displays the billing date, the amount charged, payment status (paid, failed, or pending), and a link to download the PDF receipt. This history is invaluable for resolving billing questions or investigating payment issues.

For subscriptions with metered line items, the usage section shows current period usage. You can see recorded usage quantities, the calculated charges based on usage, and historical usage from previous billing periods.

### Making Subscription Modifications

The subscription detail page includes actions for modifying the subscription. These administrative tools let you handle customer requests or resolve issues without requiring API calls.

**Change Plan** opens an interface for upgrading or downgrading the customer. Select the new plan, choose the proration behavior (immediate charge, end of period change, or no proration), and apply the change. The interface shows a preview of any prorated charges before you confirm.

**Adjust Quantity** modifies the seat count for per-seat plans. Enter the new quantity, see the prorated amount that will be charged immediately, and confirm the change. The system enforces minimum and maximum seat limits configured on the line item.

**Add Plans** lets you attach additional plans to the subscription—useful when customers want to add features or add-ons. Select the plan to add, specify the quantity, and choose proration behavior. The new plan becomes part of the subscription and bills on the same cycle.

**Cancel Subscription** offers both end-of-period and immediate cancellation options. End-of-period cancellation schedules termination for the current billing period's end, allowing the customer to retain access for the time they've paid for. Immediate cancellation terminates the subscription right away, with optional prorated refunds.

These administrative actions are the same operations available through the API, but the dashboard interface provides convenience and visual feedback that's helpful for support scenarios.

### Subscription Support Tools

When customers contact support with subscription issues, the dashboard provides tools for investigation and resolution.

The **Payment Method** section shows the customer's current payment method (last four digits and card type) and provides a link to Stripe's billing portal where customers can update their payment information. You can send this portal link to customers who need to update expired cards or change payment methods.

The **Event Log** shows a history of all subscription events, including creation, modifications, payment attempts, and status changes. This timeline helps you understand exactly what happened and when, which is essential for troubleshooting.

If a subscription is in past_due status due to payment failure, the dashboard shows the failure reason (insufficient funds, card expired, authentication required, etc.) and the retry schedule. You can see when Stripe will attempt payment again and manually trigger retry attempts if the customer has fixed the issue.

For subscriptions scheduled for cancellation, you can reverse the cancellation through the **Resume Subscription** action. This restores normal auto-renewal if the customer changed their mind.

## Analytics and Reporting

The analytics section provides visibility into your subscription business metrics, helping you understand revenue trends, identify successful pricing strategies, and spot potential issues.

### Revenue Overview

The revenue dashboard shows your monthly recurring revenue (MRR) and annual recurring revenue (ARR) based on active subscriptions. These metrics exclude one-time charges and usage-based fees, focusing on predictable recurring revenue from subscription plans.

Trend charts show how MRR evolves over time, helping you identify growth patterns or concerning declines. Segmentation breaks down MRR by product, plan, or customer cohort, revealing which pricing tiers drive the most revenue.

New MRR, expansion MRR, contraction MRR, and churned MRR components help you understand the drivers behind revenue changes. New MRR comes from new subscriptions. Expansion MRR comes from upgrades and increased quantities. Contraction MRR results from downgrades. Churned MRR is lost from cancellations.

### Subscription Metrics

Beyond revenue, subscription health metrics provide operational insight. Active subscriptions show your customer base size. Churn rate indicates what percentage of customers cancel each month. Average revenue per account (ARPA) shows the typical customer value.

These metrics broken down by plan or cohort reveal patterns. If your Pro plan has much lower churn than your Basic plan, that suggests Pro customers find more value in your product. If newer cohorts have higher churn than older ones, that might indicate onboarding or product issues.

The subscription lifecycle view shows how many subscriptions are in each state at any given time. A high number of past_due subscriptions suggests payment issues that need investigation. A growing number of trialing subscriptions indicates healthy top-of-funnel activity.

### Customer Insights

Customer analytics help you understand who your customers are and how they use your product. Geographic distribution shows where customers are located, which informs currency support and localization priorities. Plan distribution reveals which tiers are most popular. Lifetime value estimates help you understand customer economics.

The cohort analysis view groups customers by when they subscribed and tracks their behavior over time. This helps answer questions like "do customers who subscribed in January have different retention patterns than those who subscribed in June?" or "how long does it take for the average customer to upgrade to a higher tier?"

### Payment Analytics

Payment success rates and failure reasons help you optimize billing operations. If you see a high rate of "card expired" failures, proactive expiration reminders might help. If "insufficient funds" failures spike at certain times of month, you might adjust billing dates.

Geographic payment success varies significantly. Understanding where you experience payment friction helps you decide whether to support additional payment methods or make other localization improvements.

### Exporting Data

All analytics views support data export to CSV or JSON for deeper analysis in external tools. Export filtered subscription lists for bulk operations, invoice data for accounting reconciliation, usage data for customer reporting, or complete datasets for custom analytics in your data warehouse.

These exports respect the current mode (test or live) and any filters you've applied, giving you precise control over what data you extract.

## Integration Management

The integrations section manages connections to external services, most importantly your Stripe account.

### Stripe Integration

Salable uses Stripe for payment processing, which means connecting your Stripe account is essential for accepting real payments in live mode.

Click **Connect Stripe** to begin the Stripe Connect onboarding flow. You'll provide your business information including legal business name, address, and entity type. Add banking information where Stripe should deposit your funds. Complete identity verification by providing identification documents as required by your jurisdiction. Review and submit your application for Stripe to process.

This onboarding process is required only in live mode. Test mode doesn't need Stripe connection because it uses Stripe's test environment automatically.

Once connected, the integrations page shows your Stripe account status and provides a link to your Stripe Dashboard where you can view detailed payment information, configure Stripe-specific settings, manage disputes and refunds, and access Stripe's reporting tools.

The integration status indicator shows whether your Stripe onboarding is complete. You can create products and plans with minimal Stripe setup—even if your account shows as incomplete. To generate checkout links in test mode, you need to complete the business type and personal details forms in Stripe's onboarding. For live mode checkout links that process real payments, you must complete full onboarding with Active status.

### Webhook Configuration

Configure webhook endpoints to receive real-time notifications of subscription events. The webhook configuration interface lets you add multiple endpoints, each with its own URL and event type selection.

Enter the webhook URL where Salable should send events. This must be a publicly accessible HTTPS endpoint. Select which event types this endpoint should receive—you might send all events to one endpoint or route different event types to different handlers.

After creating a webhook endpoint, the dashboard shows the signing secret you need to verify webhook authenticity. Copy this secret into your application's environment configuration.

The webhook detail view shows recent deliveries, including which events were sent, whether delivery succeeded or failed, and the full request and response. This delivery history is invaluable for debugging webhook issues. If deliveries are failing, you can see the exact error and manually retry individual webhooks.

Test your webhook endpoints using the **Send Test Event** button. This triggers a sample event delivery without actually creating the associated resource, letting you verify your endpoint is working correctly before real events occur.

## User Settings and Preferences

Your personal account settings are separate from organization settings and control your individual dashboard experience.

### Profile Information

Update your personal information including name, email address, password, and notification preferences. Your email address is used for account communications, password resets, and optional product updates.

Enable or disable email notifications for specific events. You might want notifications for payment failures and cancellations but not for every successful payment. Customize these preferences to stay informed without being overwhelmed.

### Security Settings

Enable two-factor authentication (2FA) for additional account security. This requires a second verification step beyond your password when logging in, typically through an authenticator app on your phone.

View active sessions to see where your account is currently logged in. Revoke sessions from the list if you notice unfamiliar locations or want to force re-authentication on all devices.

### API Keys and Access Tokens

While organization-level API keys are managed in organization settings, your personal access tokens for dashboard API usage appear in your user settings. These tokens are useful for scripting dashboard operations or building custom tooling.

Generate personal access tokens with appropriate scopes, name them descriptively to remember their purpose, and revoke them when no longer needed. Treat personal access tokens like passwords—store them securely and never commit them to version control.

## Support and Documentation Access

The dashboard includes integrated support resources to help you quickly resolve issues and learn about features.

### In-App Help

Most dashboard sections include contextual help explaining what the section does and how to use it. Look for info icons or help links near complex features to access this guidance without leaving your workflow.

The command palette (typically opened with Cmd+K or Ctrl+K) provides quick access to common actions, navigation to any section, and searching documentation. This is the fastest way to navigate the dashboard once you're familiar with it.

### Support Contact

If you can't resolve an issue through documentation, the support link in the dashboard opens a contact form where you can describe your problem and include relevant details. Support requests automatically include your organization ID and current mode, helping support staff investigate issues faster.

For urgent issues affecting production systems, clearly indicate urgency in your request. Response times vary by support tier, with critical production issues receiving priority attention.

### Status and Changelog

The status page (linked from the dashboard) shows current system status and any ongoing incidents. If you're experiencing unexpected behavior, check the status page first to see if there's a known issue affecting multiple customers.

The changelog announces new features, improvements, and important changes to the platform. Subscribe to changelog updates to stay informed about new capabilities you can leverage in your subscription business.

---

The dashboard transforms the complexity of subscription management into a visual, intuitive interface that complements the API's programmatic power. Whether you're configuring your initial pricing structure, investigating a customer support issue, or analyzing revenue trends, the dashboard provides the tools and visibility you need to operate your subscription business effectively. Combined with the API for automated operations and the comprehensive documentation for understanding concepts, you have a complete toolkit for building and managing sophisticated subscription infrastructure.
