---
description: Set up webhook event notifications. Configure destinations, verify signatures, handle retries, and monitor delivery. All the tools you need to keep your application in sync with Salable.
---

# Webhooks

## Overview

**[Webhooks](/docs/core-concepts#webhook)** are HTTP callbacks that Salable sends to your application when important events occur. They provide real-time notifications about subscription changes, usage updates, payment events, and more. Instead of constantly polling for changes, your application receives instant notifications.

## Understanding Webhook Destinations

A Webhook Destination is an endpoint on your server that receives event notifications from Salable. Each destination has a URL where events are delivered, a unique signing secret for verifying authenticity, and a selection of event types it listens to.

You can create multiple webhook destinations for different purposes and each one operates independently with its own configuration, delivery history, and retry schedule.

Every webhook destination must listen to at least one event type, but it can listen to any number of the events Salable sends.

## Available Event Types

**Subscription Events** notify you when subscriptions change state:

`subscription.created` fires when a customer successfully completes checkout and a new subscription has been created.

`subscription.updated` occurs whenever subscription details change; plan upgrades or downgrades, quantity adjustments, billing interval changes, or status transitions.

`subscription.cancelled` indicates a subscription has ended, either immediately or at the end of the current billing period.

**Usage Events** track metered billing activity:

`usage.recorded` fires when a usage subscription cycles and the last period's usage has been successfully processed.

`usage.finalised` occurs when a usage subscription has been cancelled or otherwise ends and the last usage record has been processed.

**Payment Events** keep you informed about financial transactions:

`receipt.created` occurs when a one-off line item has been purchased by the user and a receipt has been created.

**Access Control Events** notify you about customer information updates:

`owner.updated` fires when an owner's email address is updated following them successfully purchasing a plan

## Creating Webhook Destinations

Before your application can receive webhook events, you need to create a webhook destination in the Salable dashboard. This process configures where events are sent, which events to send, and generates the signing secret for verification.

### Setting Up Your First Destination

Navigate to **Webhooks** and click the **Create Webhook** button. You'll need to provide two pieces of information: the URL where events will be sent to and which event types this destination should receive.

**Webhook URL Configuration**

Enter the full URL to your webhook endpoint in the URL field (_eg_ `https://yourapp.com/webhooks/salable`). This must be a publicly accessible HTTPS endpoint that can receive POST requests.

Your endpoint should be ready to receive events before creating the destination. While Salable will retry failed deliveries, having your handler ready from the start prevents unnecessary retry cycles.

**Event Type Selection**

Select which event types this destination should receive. You must choose at least one event type, but you can select as many as needed.

### Signing Secret

After creating your webhook destination, the dashboard displays a unique signing secret. This secret is crucial for security as it proves that incoming webhooks are genuinely from Salable and haven't been forged by malicious actors.

Copy the signing secret and store it securely in your environment configuration. You'll need this secret to verify webhook signatures in your application. Never commit signing secrets to version control or expose them in client-side code.

> **Important** Each webhook destination has its own unique signing secret. If you create multiple destinations, you'll need to store each signing secret separately and use the appropriate one when verifying each destination's events.

## Editing Webhook Destinations

Webhook destinations can be modified after creation to update the URL or change which events are delivered.

To edit a destination, find it in the webhooks list and click the **Edit** button. You can update the URL to point to a different endpoint as needed.

You can also modify the event type selection. Adding new event types means the destination will start receiving those events immediately. Removing event types stops delivery of those events going forward however any currently in the process of being sent will still be sent.

> **Note** Editing a webhook destination does not change its signing secret. The same secret remains valid, so you don't need to update your verification code when editing URLs or event types.

## Deleting Webhook Destinations

When you no longer need a webhook destination, you can delete it from the webhooks list. Deleted destinations won't receive new events, and their configuration is deleted from Salable.

## Implementing Webhook Handlers

Your webhook handler is the endpoint that receives and processes events from Salable. A robust handler verifies signatures and responds quickly to avoid timeouts.

### Handler Requirements

Webhook handlers must respond within 15 seconds. If your endpoint takes longer than 15 seconds to return a response, Salable marks the delivery as failed and schedules a retry. This timeout ensures webhook delivery doesn't hang indefinitely.

Your handler should return a 2xx status code (typically 200 or 204) to indicate successful receipt. Any other status code indicates a failure and triggers a retry.

The handler receives a POST request with a JSON payload containing the event data. Reject non-POST requests with a 405 status code. The request will include a couple of important headers: `x-salable-signature` contains the HMAC signature for verification, and `x-salable-timestamp` contains the ISO 8601 timestamp when the request was sent.

### Basic Handler Structure

Here's a basic webhook handler structure in Node.js:

```javascript
import { createHmac, timingSafeEqual } from 'crypto';

export async function handleWebhook(req, res) {
    // Only accept POST requests
    if (req.method !== 'POST') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    try {
        const signature = req.headers['x-salable-signature'];
        const timestamp = req.headers['x-salable-timestamp'];
        const body = req.body;

        // Verify timestamp and signature
        if (!verifySignature(body, timestamp, signature)) {
            return res.status(401).json({ error: 'Invalid signature' });
        }

        const { type, data } = body;

        // Process the event based on type
        await processEvent(type, data);
        return res.status(200).json({ received: true });
    } catch (error) {
        console.error('Error processing webhook:', error);
        return res.status(500).json({ error: 'Processing failed' });
    }
}
```

### Signature Verification

Every webhook request includes two important headers: `x-salable-signature` contains the HMAC SHA-256 signature, and `x-salable-timestamp` contains the ISO 8601 timestamp when the request was sent. The signature is computed from a combination of the timestamp and request body using your destination's signing secret.

The verification process involves two security checks. First, verify the timestamp is recent to prevent replay attacks, requests older than 5 minutes should be rejected. Second, compute the expected signature using your signing secret, the timestamp, and the request body, then compare it to the received signature using a constant-time comparison to prevent timing attacks.

```javascript
import { createHmac, timingSafeEqual } from 'crypto';

function verifySignature(body, timestamp, signature) {
    const secret = process.env.SALABLE_WEBHOOK_SECRET;

    // Check timestamp to prevent replay attacks (5 minute window)
    const currentTime = new Date();
    const requestTime = new Date(timestamp);
    const timeWindow = 5 * 60 * 1000; // 5 minutes in milliseconds

    if (Math.abs(currentTime.getTime() - requestTime.getTime()) > timeWindow) {
        return false;
    }

    // Construct the signed payload (timestamp + body)
    const rawBody = typeof body === 'string' ? body : JSON.stringify(body);
    const payload = `${timestamp}.${rawBody}`;

    // Compute expected signature
    const expectedSignature = createHmac('sha256', secret).update(payload).digest();

    // Constant-time comparison to prevent timing attacks
    return timingSafeEqual(expectedSignature, Buffer.from(signature, 'hex'));
}
```

> **Important** Always verify both the timestamp and signature before processing webhook data. The timestamp check prevents replay attacks where old webhook requests are resent maliciously. The signature verification ensures requests genuinely came from Salable and haven't been tampered with.

### Timestamp Validation

The `x-salable-timestamp` header contains an ISO 8601 formatted timestamp indicating when Salable sent the webhook. Validating this timestamp prevents replay attacks where an attacker captures a legitimate webhook request and resends it later.

The standard validation window is 5 minutes. Reject any request with a timestamp older than 5 minutes or in the future by more than 5 minutes. This window accounts for minor clock drift between systems while still protecting against replay attacks.

If your webhook processing includes time-consuming operations that might exceed the 15-second timeout, ensure the timestamp validation happens before those operations. The timestamp check is fast and should always complete within the timeout window.

## Retry Behaviour and Failed Deliveries

Salable automatically retries failed webhook deliveries to ensure your application receives important events even when temporary issues occur. Understanding retry behaviour helps you design handlers that work reliably.

### Automatic Retry Schedule

After a webhook delivery fails, Salable will schedule a retry using exponential backoff.

There will be up to 10 automatic retries per event. After the 10th attempt fails, automatic retries stop. At this point, you can manually resend the event through the dashboard.

### Failed Delivery Handling

Monitor the webhook delivery dashboard to track failed deliveries. Each failure includes the error message and status code returned by your endpoint, helping you diagnose any issues.

When you see failed deliveries, investigate the error message, fix the underlying issue in your handler or infrastructure, and then manually resend the event. The dashboard's resend feature lets you retry individual events once you've confirmed your endpoint is working correctly.

## Resending Events

The webhook dashboard provides tools for manually resending events in three scenarios: pending events, failed events, and successful events.

### Resending Pending Events

Pending events are scheduled for future delivery as part of the retry schedule. If you've fixed an issue with your endpoint and don't want to wait for the scheduled retry, you can resend a pending event to bring it forward to the current time. The event will be sent immediately rather than waiting for the next scheduled retry.

### Resending Failed Events

After the automatic retry limit is exhausted, you can manually resend failed events from the dashboard. Fix the issue that caused the failure, then click the **Resend** button on the failed event. Salable will attempt delivery again immediately.

### Resending Successful Events

You can also resend events that were successfully delivered. This is useful for debugging, testing changes to your webhook handler, or replaying events if you need to rebuild derived data.

When you resend a successful event, it's treated as a brand new delivery attempt. Your handler will receive the event again with the same payload. This is where idempotent processing becomes critical—your handler should recognize it's already processed this event ID and skip reprocessing to avoid duplicate effects.

## Monitoring Webhook Deliveries

The webhook delivery dashboard provides complete visibility into event transmission. For every destination, you can view all sent events, their delivery status, and detailed information about each attempt.

### Delivery History

Each webhook destination has a delivery history showing every event sent to that endpoint. The history includes the event type, timestamp, current status (pending, success, or failed), and a summary of delivery attempts.

Click on any event to view its complete details. This includes the full JSON payload sent to your endpoint, all delivery attempts with their status codes and error messages, request and response headers, and timing information.

### Event Payloads

The dashboard displays the complete payload for each generated event.

### Delivery Attempts

Each event shows the delivery attempts for each destination it was sent to. If an event failed and was retried multiple times, you'll see every attempt with its timestamp, status code, and any error message.

This history helps you understand patterns in failures. If every attempt times out after exactly 15 seconds, you know your handler is too slow. If attempts return 500 errors, there's likely a bug in your handler. If early attempts failed but later ones succeeded, you can correlate success with deployments or infrastructure changes.

## Testing Webhook Handlers

Thorough testing ensures your webhook handler works correctly before real events arrive. Test Mode provides a safe environment for webhook development without affecting production data or processing real payments.

### Test Mode Webhooks

Webhook destinations created in Test Mode only receive events from Test Mode actions. When you complete a test checkout or record test usage, those events go to Test Mode webhook destinations with their associated signing secrets.

This separation ensures test events never reach production handlers and production events never reach test handlers. You can safely experiment with webhook configuration, test signature verification, and trigger failure scenarios without any risk to your production system.

## Troubleshooting

Common webhook issues and their solutions.

### Signature Verification Failures

If signature verification consistently fails, verify you're using the correct signing secret from the webhook destination's detail page. The signed payload must combine the timestamp and body in the format `${timestamp}.${body}`, where the body is the raw JSON string before parsing.

Ensure you're using HMAC SHA-256 for computing signatures and using `timingSafeEqual` for comparison to prevent timing attacks. The signature in the `x-salable-signature` header is hex-encoded, so convert it to a Buffer when comparing with your computed signature.

Common issues include forgetting to include the timestamp in the payload, using the parsed JSON object instead of the raw body string, or comparing strings instead of using constant-time comparison. If timestamps are being rejected, verify your server's clock is synchronized—clock drift beyond the 5-minute validation window will cause rejection.

### Timeout Issues

If deliveries consistently time out, your handler is taking too long to process events. Profile your handler to identify slow operations. Consider moving time-consuming work to background jobs, acknowledge receipt quickly by returning a success response, then process the event asynchronously.

### Events Not Arriving

If you're not receiving expected events, verify the webhook destination is configured to receive that event type. Check that your endpoint URL is correct and publicly accessible.

Review the webhook delivery dashboard to see if events were sent and what responses your endpoint returned. If events were sent but failed, the delivery details show the error. If events weren't sent at all, verify the webhook destination's event type configuration.

## Next Steps

Now that you understand webhooks, explore these related guides:

- **[Testing & Development](/docs/testing-and-development)** - Test webhook handlers in Test Mode
- **[Subscriptions & Billing](/docs/subscriptions-and-billing)** - Understand subscription lifecycle events
- **[Metered Usage](/docs/metered-usage)** - Process usage events and finalization
