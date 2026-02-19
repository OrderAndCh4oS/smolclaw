---
description: Charge customers based on what they actually consume. Track API calls, storage, messages, or any measurable activity in your application. Salable calculates charges at the end of each billing cycle and adds them to the invoice automatically.
---

# Metered Usage

Fixed subscription fees don't work for every business model. When your costs scale with customer activity—API calls, storage, processing time—you need pricing that reflects actual consumption. Metered billing lets you charge for what customers use, aligning your revenue with the value you deliver.

## How Metered Billing Works

You define a **[Meter](/docs/core-concepts#meter-slug)** for each type of usage you want to track—`api_calls`, `storage_gb`, `messages_sent`. Meters belong to your organisation and can be reused across Plans at different rates: your Basic Plan might charge $0.01 per API call, while Pro charges $0.005.

When a customer subscribes to a Plan with a **[Metered Line Item](/docs/core-concepts#metered-line-item)**, Salable creates a **[Usage Record](/docs/core-concepts#usage-record)** to track their consumption. Throughout the billing period, you record usage via the API using the **[Owner](/docs/core-concepts#owner)** identifier and Meter slug. At period end, Salable finalises the count, calculates charges, and generates an Invoice.

```
Subscription Created
  └─ Usage Record created (count: 0)
      │
      ├─ You record usage → count increments
      ├─ You record usage → count increments
      │
Billing Period Ends
  └─ Usage Record finalised
      └─ Charge calculated → Invoice generated
          └─ New Usage Record created (count: 0)
```

The Owner is typically a user ID for individual Subscriptions, or an organisation/team ID for shared Subscriptions. Usage is tracked at the Owner level regardless of how many Grantees access the Subscription.

## Setting Up Metered Billing

### Adding Metered Line Items to Plans

You can create Meters inline while building Plans. In the Product editor, navigate to the Plan and click Add Line Item.

Fill in a descriptive Line Item Name, such as "API Usage". This appears on Stripe Invoices, so use customer-facing language. Leave Interval Type set to Recurring since metered charges repeat each billing cycle.

Under Pricing Type, select Metered. Choose your Billing Scheme: Per Unit multiplies the Price by the usage quantity, while Tiered offers volume-based or graduated pricing based on usage levels.

In Select Meter, choose an existing Meter or create one by typing the slug you want (like `api_calls` or `photo_generations`) and clicking Create. The Meter registers with Salable and Stripe immediately.

### Configuring Metered Pricing

After selecting your Meter, set up pricing for each billing Interval and Currency.

Click Add Price and select your Billing Interval (Month, Year, etc.). Click Add Currency and choose your Currency (USD, GBP, EUR, etc.).

For per-unit pricing, enter the Unit Amount as Price per unit. To charge $0.01 per API call, enter `0.01`.

For tiered pricing, configure each tier with its range and pricing: First Unit is auto-calculated from the previous tier, Last Unit is the upper limit or `inf` for the final tier, and Unit Amount is the Price per unit. Optionally add a Flat Amount as a base fee for reaching each tier.

**Example Per-Unit Pricing:**

```
Meter: api_calls
Price: 0.01 (= $0.01 per call)
Usage: 5,000 calls
Charge: 5,000 × $0.01 = $50.00
```

**Example Graduated Tiered Pricing:**

```
Tier 1: 1–10,000 calls at $0.01 each
Tier 2: 10,001–50,000 calls at $0.008 each
Tier 3: 50,001+ calls at $0.005 each

Usage: 60,000 calls
Charge: (10,000 × $0.01) + (40,000 × $0.008) + (10,000 × $0.005) = $470.00
```

## Recording Usage

### API: Record Usage

Record usage returns `204` immediately while processing happens in the background, so you can track millions of events without impacting your application's performance.

**Endpoint:** `POST /api/usage/record`

**Request Body:**

```json
{
    "owner": "company_acme",
    "meterSlug": "api_calls",
    "increment": 50
}
```

**Parameters:**

- **owner**: identifier for the entity being charged (user ID, organisation ID, or team ID)
- **meterSlug**: Meter identifier to increment (must match a Meter in the customer's Subscription)
- **increment**: amount to add to the usage counter (minimum 1)
- **idempotencyKey** (optional): unique key to prevent duplicate increments; requests with the same key are deduplicated

**Response:**
Returns `204 No Content` on success. No response body. Absence of an error means success.

> **Note** The Usage Record must exist, which happens automatically when a customer subscribes to a Plan with that Metered Line Item. Recording usage for an `owner` and `meterSlug` combination without an active Subscription returns `404 Not Found`.

### Implementation Example

```javascript
async function recordUsage(owner, meterSlug, increment) {
    const response = await fetch('https://api.salable.app/api/usage/record', {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${process.env.SALABLE_SECRET_KEY}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ owner, meterSlug, increment })
    });

    if (!response.ok) throw new Error(`Failed to record usage: ${response.status}`);
}

// Record after processing a request
app.post('/api/analyze-image', async (req, res) => {
    const result = await analyzeImage(req.body.imageUrl);
    await recordUsage(req.user.organizationId, 'api_calls', 1);
    res.json(result);
});
```

For high-volume scenarios, increment batches locally (every minute or every 100 calls), then record the accumulated total.

## Retrieving Usage Data

### API: List Usage Records

**Endpoint:** `GET /api/usage/count`

**Query Parameters:**

- `owner` (required): Owner identifier
- `meterSlug` (required): Meter slug to query
- `status` (required): One or more statuses, comma-separated (`recorded`, `current`, `final`)
- `before` (optional): Cursor for pagination (previous page)
- `after` (optional): Cursor for pagination (next page)

**Example Request:**

```bash
GET /api/usage-records?owner=company_acme&meterSlug=api_calls&status=current
```

**Example Response:**

```json
{
    "type": "list",
    "data": [
        {
            "id": "UsageRecord_01HXXX",
            "organisation": "org_xxx",
            "ownerId": "Owner_01HYYY",
            "usageId": "Usage_01HZZZ",
            "status": "current",
            "count": 5432,
            "recordedAt": null,
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-01-15T14:23:11Z"
        }
    ],
    "previousCursor": null,
    "nextCursor": null,
    "hasMore": false
}
```

**Response Fields:**

- **status**: record state (`recorded`, `current`, or `final`)
- **count**: accumulated usage for this period
- **recordedAt**: null for current records; set when finalised

Query with `status=current` for real-time usage dashboards, or `status=final` to retrieve historical billing periods. Results are sorted by creation date in ascending order; use `nextCursor` and `previousCursor` for pagination.

## Billing Cycle Behaviour

Metered usage operates on the Subscription's billing cycle. If a customer subscribes on January 15th with monthly billing, usage periods run January 15th to February 15th, then February 15th to March 15th.

At period end, Usage Records transition from `current` to `final` status. The accumulated count is used to calculate charges and generate an Invoice. The counter resets to zero, and a new Usage Record is created for the next period.

### Immediate Finalisation

Certain mid-cycle changes trigger immediate finalisation and a prorated Invoice:

- A Plan with Metered Line Items is removed from a Subscription
- A Subscription is cancelled immediately (not at period end)
- A Subscription's billing anchor changes

For end-of-period cancellation, usage accumulates normally until period end, then finalises on schedule.

---

You've now seen how to set up Meters, attach them to Plans with per-unit or tiered pricing, record usage via the API, and retrieve usage data for dashboards or historical analysis. Salable handles the billing cycle, finalisation, and Invoice generation automatically.

For more on configuring Products and pricing models, see the [Products & Pricing guide](/docs/products-and-pricing). For managing team access and understanding how Owners scope usage data, see [Grantees & Groups](/docs/grantee-groups).
