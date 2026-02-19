---
description: Test everything before processing real payments. Salable's Test Mode is a complete sandbox with its own Products, Subscriptions, API keys, and data. Develop features, test edge cases, and validate changes with full Stripe test card integration. No risk to production.
---

# Testing & Development

## Overview

Ensuring your Salable payment model is setup appropriately and working as intended is crucial before handling real payments from customers. Salable's [Test Mode](/docs/core-concepts#test-mode-vs-live-mode) provides a complete sandbox environment where you can experiment freely, validate your Payment Integration, and test your Subscription flows without any risk to customer experience.

Test Mode isn't just a checkbox or flag—it's a fully functional parallel environment with its own Products, Subscriptions, API keys, and data. With Test Mode you can develop new features, test edge cases, or validate changes with confidence. Test Mode also integrates with [Stripe's test infrastructure](https://docs.stripe.com/testing-use-cases) for realistic payment simulation.

This guide walks you through effective testing strategies, from initial integration development through ongoing feature work and eventual production deployment. Understanding how to leverage Test Mode fully accelerates your development cycle and prevents production issues that can erode customer trust.

## Test Mode Fundamentals

### Complete Environment Isolation

Remember, Test Mode and Live Mode are entirely separate environments. When you create a Product in Test Mode, it exists only in Test Mode—it doesn't appear in Live Mode. This isolation extends to every resource: Plans, Subscriptions, Carts, Usage Records, Entitlements, Grantee Groups etc.

You can create test Products with experimental pricing, simulate Subscription lifecycles, test edge cases that would be difficult to reproduce in production, and validate integration changes without any possibility of affecting real customers.

The only difference between Test Mode and Live Mode is that Test Mode doesn't process real money. All payments use Stripe's test environment, thus official payments are never executed.

> **Note** Test Mode API keys can only access Test Mode data. Additionally Webhooks are also segregated, with test events sent to test webhook endpoints and production events sent to production endpoints.

### Stripe Requirements

Both Test and Live Mode require a Stripe account connected through Payment Integrations. Once connected, you can build your pricing structure—creating Products, configuring Plans, and setting up Line Items—even with minimal Stripe account setup.

To generate checkout links in Test Mode, you must complete two forms in the Stripe Connect onboarding process: the **business type** form and the **personal details** form. Without completing both forms, Stripe will reject checkout link generation with an error. You don't need to complete full onboarding (banking details, identity verification) for Test Mode checkout links to work.

Live Mode however requires the full Stripe Connect onboarding process to be completed. While you can create Products and Plans with incomplete onboarding, generating functional checkout links requires your Stripe account to be fully onboarded with **Active** status, including banking information and identity verification.

Stripe's test environment accepts special test card numbers that simulate different scenarios. The card number `4242 4242 4242 4242` always succeeds. The number `4000 0000 0000 0002` always declines. Other test cards simulate specific scenarios like authentication requirements, insufficient funds, or expired cards. [Read about Stripe test environments here](https://docs.stripe.com/testing-use-cases).

## Setting Up Your Test Environment

### Initial Configuration

Begin by ensuring you're in Test Mode—check the mode indicator in the dashboard sidebar. If you're in Live Mode, switch to Test Mode before proceeding.

Start by creating your Product(s) how you would intend to on Live Mode. This may be a single Product if you're testing a simple Subscription model, or multiple Products if you offer different services or add-ons.

Next configure Plans for your test Products with the pricing models you have in mind. For example a Basic Plan at $29/month, a Pro Plan at $79/month, and a Premium Plan at $99/month. Create and include the same Entitlements you'll use in production so you can test feature access correctly.

Ensure your test data is accurate to make sure your are simulating a production level environment.

### Test API Keys

Generate test API keys from the organization settings in the dashboard. These keys grant access only to Test Mode data.

Store test API keys in your development environment's configuration, typically as environment variables. Use separate configuration for development, staging, and production environments, ensuring that each environment uses appropriate API keys and points to the correct Salable endpoints.

```bash
# .env.development
SALABLE_API_KEY=test_abc123...
SALABLE_BASE_URL=https://api.salable.app/test

# .env.production
SALABLE_API_KEY=live_xyz789...
SALABLE_BASE_URL=https://api.salable.app/live
```

This configuration separation prevents accidentally using production keys during development or test keys in production.

### Webhook Configuration for Testing

You can configure test webhook endpoints that point to your development or staging servers. For local development, hosting tools such as [ngrok](https://ngrok.com/) provide public URLs that forward to your local development server, allowing Salable to deliver webhooks to your development environment.

```bash
# Start ngrok to expose local port 3000
ngrok http 3000

# Use the ngrok URL as your test webhook endpoint
# Example: https://abc123.ngrok.io/webhooks/salable
```

Configure this ngrok URL as a test webhook endpoint in the Salable dashboard. Select the event types you want to receive, and save the signing secret for verifying webhook authenticity.

As you develop your webhook handler, the dashboard's webhook delivery log shows each event sent to your endpoint, the payload, your endpoint's response, and whether delivery succeeded. This visibility accelerates webhook development by making it easy to see what's being sent and how your endpoint responded.

## Testing Checkout Flows

### Basic Subscription Purchase

The fundamental flow to test is a customer successfully subscribing to a Plan. This validates that your entire checkout integration works end-to-end.

Start by creating a Cart in your application using your test API key. Add a Plan to the Cart and generate a checkout link athennd navigate to it in your browser.

Stripe's checkout page loads in Test Mode, indicated by a "Test Mode" badge. Enter test payment information using Stripe test cards. Use the card number `4242 4242 4242 4242`, any future expiry date, any CVC, and any postal code.

Complete the checkout flow by clicking the payment button. Stripe processes the test payment instantly and redirects you to your configured success URL. Shortly after, your webhook endpoint receives a `Subscription.created` event.

Verify the Subscription appears in the Salable dashboard under Subscriptions. Check that your application provisioned access correctly—the customer should have the Entitlements associated with their Plan.

### Testing Payment Failures

Payment failures are inevitable and it is important to handle these events gracefully. Stripe also provides test card data that fails or declines payments and can be used to genereate test payment failure events.

Use the card number `4000 0000 0000 0002` which always declines with a generic decline code. The error message will indicate that the card has declined.

Use the card number `4000 0000 0000 9995` which declines with an "insufficient funds" error.

Test authentication requirements using the card number `4000 0025 0000 3155` which requires 3D Secure authentication. Complete the authentication challenge in the test flow to verify your checkout process handles authentication correctly.

### Testing Different Currencies

If you intend to support multiple currencies, it is recommended to test the checkout flow with each one. Create Carts specifying different currencies and verify that checkout displays amounts correctly, Stripe processes payments in the expected currency, and Subscriptions are created with correct pricing.

### Team Subscription Checkout

For applications with team-based Subscriptions, test the complete team onboarding flow. Create a Grantee Group and add members to it. Next create a Cart with a per-seat Plan, assign the Grantee Group to the Cart item with the appropriate quantity.

Complete checkout and verify that all team members receive appropriate Entitlements. Test adding members after Subscription creation to validate seat management works correctly.

## Testing Subscription Management

### Upgrade and Downgrade Flows

We can also test Plan upgrades and downgrades with the test Subscriptions we have just created. In your application's Subscription management interface, trigger a Plan upgrade or downgrade from Basic to Pro. Verify that the API request succeeds, the necessary proration charges are calculated correctly, Entitlements update immediately to reflect the new Plan, and your application UI updates to show the new Plan.

### Quantity Adjustments

For per-seat Plans, you should test increasing and decreasing seat quantities. Verify that quantity increases succeed and charge prorated amounts, quantity decreases succeed but respect minimum seat requirements, attempts to reduce below minimum seats are rejected appropriately, and Grantee Group size constraints are enforced if applicable.

### Adding and Removing Plans

Test adding add-ons or additional Products to existing Subscriptions. Create another Subscription for one of your test Products, then use the Subscription modification API to add an add-on or another Product. Verify the new Plan appears on the Subscription, is included in invoices, and grants its Entitlements to the customer.

Test removing Plans by selecting a Subscription item and deleting it. Verify that the Plan is removed, associated Entitlements are revoked, and the customer isn't charged for the removed Plan in future billing cycles. Verify that attempts to remove the last Plan from a Subscription are rejected—Subscriptions must always have at least one Plan.

### Cancellation Testing

Test both types of cancellation to verify your implementation handles each correctly. Cancel a Subscription with end-of-period timing and verify that it remains active until the billing period ends, the customer retains access until the scheduled cancellation date, no refund is issued, and your application shows the upcoming cancellation to the customer.

Test immediate cancellation and verify that the Subscription terminates right away, Entitlements are revoked immediately, a prorated refund is issued if configured, and your application handles the sudden access revocation appropriately.

Test reversing scheduled cancellations by resuming a Subscription after scheduling end-of-period cancellation. Verify that the Subscription continues to auto-renew normally.

## Testing Metered Usage

### Recording Usage

If you have metered Line Items you can test that the usage is being recorded correctly. In your application, trigger actions that should record usage—making API calls, consuming storage, or whatever your metered metric is.

Verify that usage recording API calls succeed, the correct quantity is recorded, and the slug correctly identifies the usage type. Test idempotency by sending the same slug multiple times for the same owner in the same billing period—verify that the quantity updates rather than accumulating.

Test usage recording across multiple billing periods. Record usage, wait for the Subscription to bill (or manually advance time in your test if you're not actually waiting days), and verify that usage records finalize and appear on the invoice.

### Checking Current Usage

Test your application's usage display by retrieving current usage counts through the API and displaying them to customers. Verify that counts are accurate, update in real-time as usage is recorded, and reset appropriately at the start of new billing periods.

If your application enforces usage limits, test that these limits work correctly. Record usage up to the limit and verify that your application prevents further usage or prompts the customer to upgrade.

### Cross-Plan Metering

If you use the same metered slug across multiple Plans (such as shared API call tracking for Basic and Pro Plans at different per-unit prices), verify that usage recorded against one slug appears correctly on invoices for Subscriptions with different Plans, each customer is charged at their Plan's rate, and a single usage counter tracks consumption regardless of which Plan the customer has.

This shared metering is powerful but requires careful testing to ensure billing calculates correctly.

## Testing Entitlements and Access Control

### Entitlement Checking

It is crucial to test that your customers have access to features through the corresponding Entitlements as intended. In your application, call the Entitlement check API with a Grantee ID and Entitlement name, then verify that the response accurately reflects the user's Subscription status.

Test positive cases where users should have access—verify that subscribed users with the appropriate Plan receive positive Entitlement checks. Test negative cases where users shouldn't have access—verify that unsubscribed users, users on Plans without the Entitlement, and users with canceled Subscriptions receive negative Entitlement checks.

Test timing boundaries by checking Entitlements immediately after Subscription creation, right before Subscription expiry, immediately after cancellation, and during trial periods. These boundary conditions surface timing bugs that might grant or deny access incorrectly.

### Grantee Group Access

For team Subscriptions, test that all members of a Grantee Group receive Entitlements from the group's Subscription. Add a user to a group associated with a Subscription, check that user's Entitlements, and verify they have access to features granted by the group Subscription.

Test removing users from groups and verify that their Entitlements update appropriately. If they have no other Subscriptions granting those Entitlements, they should lose access immediately.

Test users who belong to multiple Grantee Groups with different Subscriptions. Verify that they receive the union of Entitlements from all groups—if one group Subscription grants `feature_a` and another grants `feature_b`, the user should have both.

### Entitlement Expiry

If you use Entitlements with expiry dates, test that access is correctly granted before expiry and denied after. This typically involves creating Entitlements with expiry dates in the near future, checking access before and after the expiry timestamp.

## Testing Webhook Handling

### Event Processing

Your webhook handler needs to process various event types correctly. Trigger each important event type in Test Mode and verify your handler processes it appropriately.

Create Subscriptions to trigger `subscription.created` events. Verify your handler provisions access, updates your database, or performs whatever initialization your application requires for new Subscriptions.

Modify Subscriptions to trigger `subscription.updated` events. Verify your handler detects the changes and updates your application state accordingly.

Cancel Subscriptions to trigger `subscription.canceled` events. Verify your handler revokes access and updates Subscription status in your system.

Use Stripe test cards that fail to trigger `payment.failed` events. Verify your handler notifies customers and tracks the failure appropriately.

### Idempotency Testing

Webhook deliveries can be duplicated, so your webhook handlers must be idempotent. Test this by manually resending the same webhook event multiple times through the dashboard's webhook delivery interface.

Verify that processing the same event multiple times has the same effect as processing it once—no duplicate records are created, no double provisioning occurs, and no multiple notifications are sent.

The event ID included in webhook payloads is your tool for implementing idempotency. Store processed event IDs and skip events you've already seen.

### Error Handling

Test how your webhook handler behaves when processing fails. Introduce errors in your handler code (perhaps by commenting out database access temporarily) and observe webhook deliveries failing.

Verify that Salable retries failed deliveries according to the documented retry schedule. Check the dashboard's webhook delivery log to see retry attempts. Fix the error in your handler and verify that a subsequent retry succeeds.

This testing ensures your production system can recover from transient issues without losing events.

### Webhook Security

Verify that your webhook handler correctly validates signatures. Send a webhook with an invalid signature (modify the signature header before processing) and verify that your handler rejects it with a 401 response.

Send a webhook with no signature and verify rejection. Send a webhook with the correct signature and verify acceptance. This security testing ensures production webhooks can't be forged by malicious actors.

## Performance and Load Testing

### Rate Limit Verification

While developing, verify that your application handles rate limits gracefully. Intentionally send more than 100 requests per second to the API and observe the 429 responses. Verify that your client implements exponential backoff and retries appropriately.

Test that your application continues to function correctly under rate limiting—requests eventually succeed, users don't see errors, and your system doesn't enter a retry storm that makes the situation worse.

### Concurrent Operations

Test scenarios where multiple operations happen simultaneously. Create several Carts concurrently, modify the same Subscription from multiple requests, record usage from multiple sources simultaneously, and check Entitlements for many users in parallel.

Verify that your application handles concurrency correctly without race conditions, duplicates, or other issues. Database transactions, idempotency keys, and proper error handling become important here.

### Large Dataset Handling

If you expect to manage large amounts of Subscriptions or high usage volumes, make sure to test with realistic data sizes. Create dozens or hundreds of test Subscriptions, record large volumes of usage, and retrieve large Subscription lists with pagination.

Verify that pagination works correctly, your application doesn't load excessive data into memory, and performance remains acceptable with realistic data volumes.

## Integration Testing Strategies

### End-to-End Test Suites

Build automated test suites that exercise complete flows from your application through Salable to Stripe and back. These tests give you confidence that the entire system works together correctly.

An end-to-end Subscription test might programmatically create a Cart, add a Plan, generate a checkout link, simulate completing checkout (using test cards), wait for the webhook, verify the Subscription was created, check Entitlements, and verify your application's state is correct.

### Continuous Integration

Integrate your test suite into your continuous integration pipeline. Configure your CI environment with Test Mode API keys, run the full test suite on every commit or pull request, and block deployments if tests fail.

## Transitioning to Production

### Pre-Launch Checklist

Before launching in Live Mode, verify your test mode data is accurate. Confirm your Test Mode integration works completely with all necessary flows tested, including success paths, error handling, edge cases, and webhook processing. Ensure your Stripe Connect connection is established in Live Mode and, critically, that your Stripe Connect onboarding is fully complete with an **Active** status—incomplete Stripe Connect accounts will prevent checkout links from working.

Once you are satisfied that your test Products are accurate, you can simply navigate to the Product configuration page and click the Copy to Live Mode button. This will copy over your Product and all corresponding data (Plans, Line Items etc) over to Live Mode.

Make sure to update your application configuration to use Live Mode API keys and endpoints. Configure production webhook endpoints with appropriate URLs and verify they're reachable.

### Gradual Rollout

You may want to consider launching to a limited audience initially rather than opening to all customers immediately. This limited rollout lets you verify production behavior with real customers and real money while limiting the impact of any undiscovered issues.

Monitor error rates, webhook delivery success, payment success rates, and customer feedback during initial rollout. If everything looks good, expand access to your full customer base.

### Production Monitoring

Once live, it is best to monitor key metrics continuously. Track Subscription creation rates and success/failure patterns, payment success rates and decline reasons, webhook delivery success and processing times, Entitlement check response times, and error rates across all API operations.

Set up alerts for anomalies like sudden spikes in payment failures, webhook delivery failures, API error rates, or unexpected drops in Subscription creation. These alerts let you respond quickly to issues before they affect many customers.

## Common Testing Scenarios

### Free Trial to Paid Conversion

Test the complete trial lifecycle by creating a Plan with a trial period, subscribing a test customer, verifying they have full access during the trial, simulating time passing (or noting when the trial will end), and verifying that billing occurs correctly when the trial ends.

Test trial cancellation by canceling before the trial ends and verifying the customer is never charged.

### Team Onboarding Flows

Test the complete team signup journey where an administrator creates an account, invites team members before purchasing, subscribes to a team Plan with appropriate seat quantity, and all team members receive access immediately.

Test team management after purchase by adding members, adjusting seat quantities, removing members, and verifying Entitlements update correctly for all team members.

### Complex Multi-Plan Subscriptions

For customers who purchase multiple Products or add-ons together, test creating Carts with multiple Plans, completing checkout, verifying all Plans appear on the Subscription, and checking that all Entitlements from all Plans are granted.

Test modifying these multi-Plan Subscriptions by adding additional Plans, removing some Plans while keeping others, and changing quantities on specific Plans.

### Migration from Other Systems

If you're migrating existing customers from another billing system to Salable, test your migration process thoroughly. Create test data representing your existing customer structures, run your migration scripts against Test Mode, verify Subscriptions are created correctly with proper billing dates, and ensure Entitlements map correctly from old system to new.

## Debugging and Troubleshooting

### API Response Inspection

When tests fail or behavior doesn't match expectations, examine API responses carefully. The detailed error messages include error codes for programmatic handling, human-readable messages explaining what went wrong, and details about validation failures or constraint violations.

Enable detailed logging in your application to capture all API requests and responses during development.

### Dashboard Investigation

Use the Salable dashboard to investigate issues from a different angle. View the resources your API calls created or modified, check Subscription states and histories, review webhook delivery logs and event payloads, and examine usage records and invoice Line Items.

The dashboard provides visibility that complements API logs, often making issues obvious that would be opaque looking only at API request/response logs.

### Webhook Replay

When webhook handling issues occur, use the dashboard's webhook replay feature to resend events to your handler. This lets you fix bugs in your handler and reprocess events without recreating entire Subscription scenarios.

The replay preserves the original event ID, so make sure your idempotency checking allows for replays during development—you might need to clear your processed events table or add a development mode bypass.

### Support Resources

If you encounter issues you can't resolve, Salable support can help. When contacting support, include relevant Subscription IDs, API request/response details including full JSON payloads, webhook event IDs and payloads if applicable, and descriptions of what you expected versus what actually happened.

This context helps support staff diagnose issues quickly and provide specific solutions.

---

Thorough testing in Test Mode is your foundation for reliable Subscription management. By methodically testing checkout flows, Subscription management, usage tracking, Entitlements, and webhooks before launching, you prevent production issues that erode customer trust and create support burden. The investment in comprehensive testing pays dividends through smooth production operations, confident deployments, and customer experiences that work correctly the first time.
