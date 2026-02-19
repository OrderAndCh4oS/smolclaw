---
description: Every SaaS app faces the challenge of keeping feature access synchronised with billing. Entitlements put you in control of which features each plan unlocks, while Salable takes care of the Subscription from purchase to cancellation.
---

# Understanding Entitlements

Every SaaS app faces a challenge: keeping feature access synchronised with billing. When a customer subscribes, they need immediate access. When they upgrade, new features should unlock instantly. When a payment fails or a Subscription ends, access must be revoked.

**[Entitlements](/docs/core-concepts#entitlement)** are Salable's answer to this problem. An Entitlement is a string identifier—such as `analytics` or `sso`—that grants access to a feature in your application. You define Entitlements for each feature you want to gate, attach them to **[Plans](/docs/core-concepts#plan)**, and then check whether a user has them before granting access.

You can focus on building features and defining which Plans include them—Salable handles the complex logic of tracking Subscription status, managing grace periods, and ensuring access stays perfectly synchronised with billing.

## How Entitlements Work

**[Subscriptions](/docs/core-concepts#subscription)** have a **[Group](/docs/core-concepts#group)** associated with them. All **[Grantees](/docs/core-concepts#grantee)** in a Group receive the Entitlements from that Subscription's Plan. A Grantee can belong to multiple Groups and receive Entitlements from each.

> **Note** Only Subscriptions to Plans with a per-seat Line Item have Groups attached.

Example:

```
Plan "Pro"
  ├─ Entitlements: ['analytics', 'api_access', 'export_csv']
  └─ Subscription (active)
      └─ Group "Acme Corp"
          └─ Grantee "user_123"
              └─ Has: analytics, api_access, export_csv
```

### Lifecycle in Action

Salable automatically adjusts access when Subscriptions change:

**Subscription created or renewed:** Entitlements are immediately available. When a Pro Subscription is created, `analytics` and `api_access` are granted instantly.

**Subscription upgraded:** New Entitlements are added. When a Subscription upgrades from Pro to Enterprise, `sso` and `priority_support` are granted immediately.

**Subscription downgrade:** Entitlements are removed. When a Subscription downgrades from Enterprise to Pro, access to `sso` and `priority_support` is revoked.

**Payment fails (past_due):** You can control whether access continues. If "Return Entitlements While Past Due" is enabled on the Product, access continues while Stripe attempts to recover payment. If disabled, access is revoked immediately.

**Subscription cancelled:** Entitlements are revoked. When the Subscription ends, access stops—no manual intervention required.

## Attaching Entitlements to Plans

You can create and manage Entitlements while creating or managing your Plans. In the Product management view, each Plan has a Select Entitlements field that lets you search existing Entitlements or create new ones—type a name to filter, or enter a new name to create it. Once created, an Entitlement can be reused across any of your Plans.

### Naming Your Entitlements

Entitlement names must use lowercase letters with underscores (snake_case). No spaces, hyphens, or special characters.

**Valid:** `api_access`, `advanced_features`, `priority_support`

**Invalid:** `API_Access` (uppercase), `api-access` (hyphens), `api access` (spaces), `api_access_` (trailing underscore)

There are two common conventions for selecting Entitlement names:

**Feature-based naming** ties Entitlements to specific capabilities: `api_access`, `export_data`, `custom_reports`. This offers granular control—you can mix and match Entitlements across Plans, create bespoke Subscriptions for specific customers, and easily move features between tiers as your pricing evolves.

**Tier-based naming** bundles features by plan level: `basic_features`, `pro_features`, `enterprise_features`. Although convenient and intuitive at first this convention and cause limitations if you later need to sell individual features separately or create custom arrangements for enterprise customers.

You can combine both approaches based on your needs.

## Checking Entitlements

If a Grantee has access to multiple Subscriptions—say a base plan plus an analytics add-on—they receive Entitlements from all of them. Entitlements are returned from Subscriptions that are `active`, `trialing`, or optionally `past_due` if you've enabled "Return Entitlements While Past Due" on the Product.

### Via the Dashboard

To verify a user's access, navigate to Entitlement Check in the dashboard. Enter a Grantee ID and click Check Grantee to see their current Entitlements.

### Via the API

**Endpoint:** `GET /api/entitlements/check`

**Query Parameters:**

- `granteeId` (required): The Grantee to check

**Example Request:**

```bash
GET /api/entitlements/check?granteeId=user_alice
```

**Example Response:**

```json
{
    "entitlements": [
        { "type": "entitlement", "value": "api_access", "expiryDate": "2026-01-15T10:00:00Z" },
        { "type": "entitlement", "value": "advanced_analytics", "expiryDate": "2026-01-15T10:00:00Z" }
    ],
    "signature": "a3f5b8c2d9e1..."
}
```

The `value` is the Entitlement name. The `expiryDate` indicates when the current billing period ends—if an Entitlement is returned, it's active, and your application should grant access. If the expiry date is in the past, the Subscription is in a grace period. If a Grantee has multiple Subscriptions providing the same Entitlement, Salable returns the expiry date furthest in the future. The `signature` can be used to verify that the response hasn't been tampered with.

For perpetual subscriptions (one-off purchases with no recurring billing), `expiryDate` will be `null`, indicating the entitlement never expires.

### Subscription Status Reference

| Status               | Returned?   | Notes                                                                                                      |
| -------------------- | ----------- | ---------------------------------------------------------------------------------------------------------- |
| `active`             | Yes         | Normal active Subscription                                                                                 |
| `trialing`           | Yes         | During trial period                                                                                        |
| `past_due`           | Conditional | Only if **[Product](/docs/core-concepts#product)** setting "Return Entitlements While Past Due" is enabled |
| `canceled`           | No          | Subscription has ended                                                                                     |
| `incomplete`         | No          | Payment not completed                                                                                      |
| `incomplete_expired` | No          | Payment attempt expired                                                                                    |
| `unpaid`             | No          | Failed to collect payment                                                                                  |

## Implementing Access Control

Authorise your API endpoints by returning a 403 when the required Entitlement is missing:

```javascript
app.get('/api/advanced-analytics', async (req, res) => {
    const { entitlements } = await getEntitlements(req.user.id);
    const hasAccess = entitlements.some(ent => ent.value === 'advanced_analytics');

    if (!hasAccess) {
        return res.status(403).json({ error: 'This feature requires a Pro Subscription' });
    }

    res.json({ data: getAdvancedAnalytics() });
});
```

On your frontend, use Entitlements to control what users see—hiding unavailable features or showing upgrade prompts:

```javascript
function AdvancedAnalytics({ entitlements }) {
    const hasAccess = entitlements.some(ent => ent.value === 'advanced_analytics');

    if (!hasAccess) {
        return <UpgradePrompt message="Upgrade to Pro to access Advanced Analytics" />;
    }

    return <AnalyticsDashboard />;
}

// Conditionally render based on entitlements
{
    entitlements.some(ent => ent.value === 'export_data') && <Button onClick={handleExport}>Export Data</Button>;
}
```

> **Important** Frontend checks may improve user experience but can be bypassed. For sensitive features, always enforce access on your backend.

## Modifying Entitlements on Active Plans

When you add or remove Entitlements from a Plan with active Subscriptions, changes take effect on the next Entitlement check.

**Adding an Entitlement to a Plan:** All existing subscribers immediately gain access to the new feature. This is useful when you're launching a new capability and want to roll it out to current customers.

**Removing an Entitlement from a Plan:** All existing subscribers immediately lose access. Make sure to communicate changes to your customers before removing Entitlements they're actively using.

## Advanced Topics

### Entitlement Signatures

Every Entitlement check response includes a cryptographic signature that proves the response came from Salable. This is useful when passing Entitlement data from your backend to your frontend—you can verify the data hasn't been tampered with.

```javascript
const crypto = require('crypto');

function verifyEntitlements(entitlements, signature, publicKey) {
    const data = JSON.stringify(entitlements);
    const verify = crypto.createVerify('sha256');
    verify.write(data);
    verify.end();
    return verify.verify(publicKey, signature, 'hex');
}
```

### Filtering by Owner

The `owner` query parameter scopes Entitlement checks to Subscriptions owned by a specific Owner. This is useful when a Grantee belongs to multiple Groups with different Subscriptions—for example, a user who works with several teams.

```bash
# Check user's access within Team A
GET /api/entitlements/check?granteeId=user_john&owner=team_a

# Check user's access within Team B
GET /api/entitlements/check?granteeId=user_john&owner=team_b
```

By including the `owner` parameter, the response also includes metered Line Item slugs, letting you check both feature access and usage permissions in a single call.

## Troubleshooting

### Entitlement Not Returned

In the case that an expected Entitlement doesn't appear:

1. Verify the Entitlement is attached to the Plan
2. Confirm the Grantee is in a Group with an active Subscription to that Plan
3. Check the Subscription status is `active` or `trialing`
4. Verify the Grantee is in the correct Group

### Entitlement Check Returns 404

A 404 indicates that the Grantee doesn't exist. Create the respective Grantee and add them to a Group with an active Subscription.
