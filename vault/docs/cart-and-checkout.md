---
description: 'Carts support multi-Plan purchases on a single Subscription, enabling plugin and add-on pricing models without requiring signup. This guide covers the flow from Cart creation to completed checkout.'
---

# Cart & Checkout

## Overview

Salables' Cart system provides a flexible way to build shopping experiences for your Subscription Products. Whether you're implementing a self-service pricing page or building a custom checkout flow, Carts let customers select multiple Plans and complete the purchase in a single transaction.

Carts support anonymous users who may not have signed up for your application, making it possible for guests to add Plans to their Cart before creating an account. When they do sign up, you simply update the Cart's Owner to link to their new account.

## How Carts Work

A Cart belongs to an [**Owner**](/docs/core-concepts#owner) (an identifier used to scope the Subscription) and contains Cart items representing the Plans the customer wants to purchase. Each Cart has a billing **interval** (_ege_ monthly, yearly etc), and can optionally specify a **currency**. If no currency is provided, Stripe determines one during checkout based on the customer's location.

When you add items to a Cart, Salable validates that the selected Plans support the Cart's currency and interval. This ensures customers only see compatible pricing options at checkout. The Cart can have three states: **active** for Carts currently being built, **complete** for Carts that have successfully checked out, and **abandoned** for Carts that were explicitly marked as no longer needed.

When the customer is ready to purchase, you simply generate a Stripe Checkout session URL from the Cart. After successful payment, a Subscription is created with the specified Grantee Groups and Entitlements.

## Cart Concepts

### Owner

The Owner is the entity responsible for paying for the Subscription. For individual Subscriptions, this might be a user ID. For team or organization Subscriptions, it's typically an organization or company ID. The Owner identifier is flexible—you choose what makes sense for your business model.

Owners are created automatically when you create a Cart. If an Owner with that identifier already exists in your organization, Salable reuses it. This means you can create multiple Carts for the same Owner without duplicating Owner records.

### Currency and Interval

**Providing an Explicit Currency (Recommended)**

It is recommended to explicitly define the currencies you would like your Product to support to provide an easier checkout experience. When you provide a currency:

- You can design different pricing strategies for different markets—offering region-specific discounts or adjusting prices based on purchasing power parity
- You can target specific currencies without needing to configure all currency options across every Line Item
- Salable cherry-picks only the Line Items that have pricing in that specific currency, ensuring customers see consistent prices from your pricing page through to Stripe checkout
- You prevent confusion from currency mismatches—what customers see on your site matches what they pay at checkout

This approach provides the most control and the most predictable customer experience.

**Omitting Currency (Geolocation Mode)**

If you opt not to specify a currency, Stripe will use geolocation at checkout to automatically determine the customer's currency. This approach has some trade-offs:

- Stripe detects the customer's location and displays prices in their local currency
- Salable includes all Line Items from the Plans in your Cart (no cherry-picking)
- The currency shown at checkout might differ from what you displayed on your pricing page if the customer is in a different region
- All Line Items across all Plans must have the same default currency (a Stripe requirement)
- You must configure pricing for all currencies you want to support across all Line Items

**Critical Requirement for Geolocation Mode**

If you omit currency, all Line Items across all Plans in your Cart must share the same default currency. This is a Stripe requirement. For example, if Plan A's Line Items default to USD and Plan B's Line Items default to GBP, the checkout will fail. In this case, you must provide an explicit currency when creating the Cart.

You don't need to specify an interval and interval count when creating a Cart, but you must provide one when adding the first item. The interval can be **day**, **week**, **month**, or **year** for plans with recurring line items. Or, for one-off line items it can be **null**. Once the first item sets the interval and interval count, all subsequent items added to the Cart must use the same interval (or currency for one off items).

### Cart Items

A Cart item represents a Plan that the customer wants to purchase. Each Cart item includes the Plan ID, optional metadata for specifying quantities above the minimum for specific Line Items, and optionally a Grantee ID or Grantee Group ID to assign access.

The metadata structure is an object where keys are Line Item slugs and values are objects with quantity information. You only need to include Line Items in metadata when setting their quantity above the configured minimum. Line items omitted from metadata automatically use their minimum quantity. Metered Line Items should never be included in metadata.

### Cart Status

Carts move through different statuses during their lifecycle. **Active** Carts are being built—you can add items, remove items, and modify them. **Complete** Carts have been successfully checked out and converted into Subscriptions. **Abandoned** Carts have been explicitly marked as no longer needed, which helps you track Cart abandonment rates.

### One-Off Purchases

Salable supports one-off purchases through the Cart system. They can be purchased individually or alongside recurring plans that share the same currency.

After purchasing a one-off item, a Receipt is generated as a proof of purchase which can be viewed in the Salable dashboard. A `receipt.created` webhook event is also emitted.

**Creating One-Off Only Carts**

For purchases that contain only one-off items (no recurring charges), create the Cart with `interval` and `intervalCount` set to `null`:

```json
{
    "owner": "company_acme",
    "currency": "USD",
    "interval": null,
    "intervalCount": null
}
```

When adding items to a one-off Cart, also set `interval` and `intervalCount` to `null`:

```json
{
    "cartId": "Cart_01HXXX",
    "planId": "Plan_01HYYY",
    "interval": null,
    "intervalCount": null
}
```

**Mixed Plans: One-Off Plus Recurring**

Plans can contain both one-off and recurring Line Items. When you add such a Plan to a Cart with a specified interval and currency:

- Recurring Line Items that match the Cart's interval and have pricing in the Cart's currency are included
- One-off Line Items that have pricing in the Cart's currency are automatically included (they don't need to match the interval)

For example, consider a Plan with three Line Items: a $99 one-time setup fee, a $29/month base subscription, and a $10/user/month per-seat charge. When you add this Plan to a monthly USD Cart, all three Line Items are included. The customer sees a checkout with the one-time setup fee plus the recurring monthly charges. The setup fee appears only on the first invoice, while the subscription and per-seat charges recur each month.

## Creating a Cart

### API: Create Cart

**Endpoint:** `POST /api/carts`

**Request Body:**

```json
{
    "owner": "company_acme",
    "currency": "USD",
    "interval": "month",
    "intervalCount": 1
}
```

Or for geolocation-based currency selection:

```json
{
    "owner": "company_acme",
    "interval": "month"
}
```

**Parameters:**
The **Owner** is a string identifier used to scope the Subscription and its related data. The **currency** is optional—provide a three-letter currency code in uppercase (automatically converted if you provide lowercase) for explicit currency selection, or omit it entirely to let Stripe use geolocation to determine the best currency for the customer. The **interval** is optional and can be set to `day`, `week`, `month`, or `year`, or omitted to set it later. The interval count can also be specified optionally with the **intervalCount** parameter which accepts a number.

**Response:**

```json
{
    "data": {
        "id": "Cart_01HXXX",
        "organisation": "org_xxx",
        "ownerId": "Owner_01HYYY",
        "currency": "USD",
        "interval": "month",
        "intervalCount": 1,
        "status": "active",
        "createdAt": "2024-01-15T10:00:00Z",
        "updatedAt": "2024-01-15T10:00:00Z"
    }
}
```

### Creating Carts for Anonymous Users

For anonymous users who haven't authenticated yet, use a temporary session identifier as the Owner. This could be a session ID from your application, a temporary UUID, or any unique identifier you can track.

```javascript
async function createAnonymousCart(sessionId, currency, interval) {
    const body = {
        owner: `session_${sessionId}`,
        interval
    };

    // Only include currency if provided
    if (currency) {
        body.currency = currency.toUpperCase();
    }

    const response = await fetch('https://api.salable.app/api/carts', {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${process.env.SALABLE_SECRET_KEY}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(body)
    });

    if (!response.ok) {
        throw new Error(`Failed to create Cart: ${response.status}`);
    }

    const { data: cart } = await response.json();
    return cart;
}

// Example: Create a Cart when user visits pricing page
app.post('/api/create-cart', async (req, res) => {
    const { sessionId, currency, interval } = req.body;

    try {
        const cart = await createAnonymousCart(sessionId, currency, interval);
        res.json({ cartId: cart.id });
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});
```

### Creating Carts for Authenticated Users

For authenticated users, use their user ID or organisation ID as the Owner identifier directly.

```javascript
async function createAuthenticatedCart(userId, currency, interval) {
    const body = {
        owner: userId,
        interval
    };

    // Only include currency if provided
    if (currency) {
        body.currency = currency.toUpperCase();
    }

    const response = await fetch('https://api.salable.app/api/carts', {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${process.env.SALABLE_SECRET_KEY}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(body)
    });

    if (!response.ok) {
        throw new Error(`Failed to create Cart: ${response.status}`);
    }

    const { data: cart } = await response.json();
    return cart;
}
```

## Adding Items to a Cart

You can add multiple different Plans to a Cart, but each Plan can only be added once. If you need multiple quantities, adjust the quantity in the Line Item metadata rather than adding the same Plan multiple times.

### API: Create Cart Item

**Endpoint:** `POST /api/cart-items`

**Request Body:**

```json
{
    "cartId": "Cart_01HXXX",
    "planId": "Plan_01HYYY",
    "interval": "month",
    "intervalCount": 1,
    "metadata": {
        "per_seat_charge": { "quantity": 5 }
    },
    "grantee": "user_alice"
}
```

**Parameters:**
The **cartId** identifies which Cart to add the item to. The **planId** specifies which Plan the customer wants to purchase. The **interval** sets or confirms the Cart's billing interval—use `day`, `week`, `month`, or `year` for recurring purchases. For adding only one-off line items, set **interval** to `null`. If the Cart already has an interval set, the value must match. The **intervalCount** works alongside interval to define the billing frequency (_eg_ `2` with `week` for biweekly billing). For one-off purchases, set **intervalCount** to `null`. The **metadata** object is optional and maps Line Item slugs to quantity objects—you only need to include Line Items where the quantity should be above the configured minimum. Line items not included in metadata will use their minimum quantity. Never include metered Line Items in metadata. The **grantee** is optional and can be a grantee ID or a group ID (starting with `grp_`).

**Response:**

```json
{
  "data": {
    "id": "CartItem_01HZZZ",
    "organisation": "org_xxx",
    "cartId": "Cart_01HXXX",
    "planId": "Plan_01HYYY",
    "metadata": { ... },
    "granteeId": "user_alice",
    "groupId": null,
    "createdAt": "2024-01-15T10:05:00Z",
    "updatedAt": "2024-01-15T10:05:00Z"
  }
}
```

### Understanding Metadata

The metadata structure specifies quantities for Line Items when you need to set them above their minimum values. Each Line Item slug maps to an object with a `quantity` property. You only need to include Line Items in the metadata when their quantity should be higher than the configured minimum—if you omit a Line Item from the metadata, Salable automatically uses the minimum quantity for that Line Item.

```javascript
// Example: Plan with three Line Items
const metadata = {
    // Only include Line Items where quantity > minimum
    user_seats: { quantity: 10 } // Per-seat Line Item, setting 10 seats
    // monthly_base would use its minimum (typically 1) if not specified
    // api_calls is metered, so it's not included here
};
```

**Important:** Do not include metered Line Items in the metadata. Metered Line Items have their quantities tracked through usage recording after the Subscription is created. Including a metered Line Item in your Cart metadata will result in an error. The quantity for metered items can only be incremented after purchase when usage is recorded.

### Adding Items Example

```javascript
async function addItemToCart(cartId, planId, interval, intervalCount, metadata, granteeId) {
    const response = await fetch('https://api.salable.app/api/cart-items', {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${process.env.SALABLE_SECRET_KEY}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            cartId,
            planId,
            interval,
            intervalCount,
            metadata,
            ...(granteeId && { grantee: granteeId })
        })
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.title);
    }

    const { data: cartItem } = await response.json();
    return cartItem;
}

// Example: Add a Plan to Cart
app.post('/api/cart/add-plan', async (req, res) => {
    const { cartId, planId, seats } = req.body;

    try {
        // Build metadata - only include Line Items with quantities above minimum
        const metadata = {};

        // Only add per-seat if quantity is above its minimum
        if (seats > 1) {
            // Assuming minimum is 1
            metadata.per_seat = { quantity: seats };
        }
        // base_subscription uses its minimum (typically 1) when not specified
        // metered Line Items are never included in metadata

        const cartItem = await addItemToCart(cartId, planId, 'month', metadata, req.user.id);

        res.json({ success: true, cartItem });
    } catch (error) {
        res.status(400).json({ error: error.message });
    }
});
```

### Validation Rules

The following validation rules are enforced when adding items to a Cart:

- The same Plan cannot be added more than once
- If the Cart has an explicit currency set, the Plan must have pricing configured for that currency and the Cart's interval.
- If the Cart's currency was omitted, all Line Items from the Plan are included.
- Quantities must be within the Line Item's minimum and maximum quantity limits. For per-seat Line Items, if you provide a Grantee Group ID, the quantity must be at least equal to the number of members in that Grantee Group.
- You cannot add a metered Line Item if the Owner already has an active Subscription with that same meter slug (to prevent duplicate usage tracking).

If [Tier Tags](/docs/core-concepts#tier-tags-and-tier-sets) are assigned to Plans, additional validation rules apply when adding items to a Cart:

- You cannot add multiple Plans with the same tier tag to the same Cart.
- You cannot add a Plan to a Cart if the Owner already has an active Subscription to another Plan with the same tier tag.

## Managing Cart Items

### Retrieving a Cart

**Endpoint:** `GET /api/carts/{cartId}`

Retrieve the full Cart with all its items, expanded metadata showing Line Item details, and quantity validation rules for each Line Item.

```javascript
async function getCart(cartId) {
    const response = await fetch(`https://api.salable.app/api/carts/${cartId}`, {
        headers: {
            Authorization: `Bearer ${process.env.SALABLE_SECRET_KEY}`
        }
    });

    if (!response.ok) {
        throw new Error(`Failed to get Cart: ${response.status}`);
    }

    const { data: cart } = await response.json();
    return cart;
}

// Display Cart contents to user
app.get('/api/cart/:cartId', async (req, res) => {
    try {
        const cart = await getCart(req.params.cartId);

        // Transform for frontend display
        const cartSummary = {
            currency: cart.currency,
            interval: cart.interval,
            cartItems: cart.cartItems.map(item => ({
                planName: item.plan.name,
                lineItems: Object.entries(item.metadata).map(([slug, details]) => ({
                    name: details.name,
                    quantity: details.quantity,
                    priceType: details.priceType
                }))
            }))
        };

        res.json(cartSummary);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});
```

### Removing Cart Items

**Endpoint:** `DELETE /api/cart-items/{cartItemId}`

Remove a specific item from the Cart. The Cart must be in **active** status to remove items.

```javascript
async function removeCartItem(CartItemId) {
    const response = await fetch(`https://api.salable.app/api/cart-items/${cartItemId}`, {
        method: 'DELETE',
        headers: {
            Authorization: `Bearer ${process.env.SALABLE_SECRET_KEY}`
        }
    });

    if (!response.ok) {
        throw new Error(`Failed to remove Cart item: ${response.status}`);
    }

    // 204 No Content response
    return true;
}
```

### Updating Cart Owner

**Endpoint:** `PATCH /api/carts/{cartId}`

Update the Cart's Owner, which is essential for converting anonymous Carts to authenticated user Carts.

**Request Body:**

```json
{
    "owner": "user_alice_authenticated"
}
```

```javascript
async function updateCartOwner(cartId, newOwnerId) {
    const response = await fetch(`https://api.salable.app/api/carts/${cartId}`, {
        method: 'PATCH',
        headers: {
            Authorization: `Bearer ${process.env.SALABLE_SECRET_KEY}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            owner: newOwnerId
        })
    });

    if (!response.ok) {
        throw new Error(`Failed to update Cart: ${response.status}`);
    }

    const { data: cart } = await response.json();
    return cart;
}
```

### Abandoning a Cart

**Endpoint:** `POST /api/carts/{cartId}/abandon`

Mark a Cart as abandoned. This is useful for tracking Cart abandonment metrics or cleaning up Carts that users explicitly closed without purchasing.

```javascript
async function abandonCart(cartId) {
    const response = await fetch(`https://api.salable.app/api/carts/${cartId}/abandon`, {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${process.env.SALABLE_SECRET_KEY}`
        }
    });

    if (!response.ok) {
        throw new Error(`Failed to abandon Cart: ${response.status}`);
    }

    // 204 No Content response
    return true;
}
```

## Anonymous to Authenticated Flow

One of the most powerful features of Salable's Cart system is support for anonymous users. This pattern lets visitors explore your pricing, add Plans to their Cart, and then sign up only when they're ready to purchase.

### Step 1: Create Anonymous Cart

When an anonymous user visits your pricing page, create a Cart using a session identifier.

```javascript
// Frontend: When user visits pricing
fetch('/api/create-anonymous-cart', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        sessionId: getSessionId(), // Your session tracking
        currency: 'USD',
        interval: 'month'
    })
})
    .then(res => res.json())
    .then(({ cartId }) => {
        // Store cartId in localStorage or state
        localStorage.setItem('cartId', cartId);
    });
```

### Step 2: Add Plans as Anonymous User

Let the anonymous user add Plans to their Cart normally. The Cart exists and functions fully before authentication.

```javascript
// Frontend: User clicks "Add to Cart" on pricing page
function addPlanToCart(planId, seats) {
    const cartId = localStorage.getItem('cartId');

    return fetch('/api/cart/add-plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            cartId,
            planId,
            seats
        })
    });
}
```

### Step 3: Prompt for Authentication

When the user proceeds to checkout, redirect them to sign up or log in if they haven't already.

```javascript
// Frontend: User clicks "Proceed to Checkout"
function proceedToCheckout() {
    if (!isAuthenticated()) {
        // Store intent to return to checkout after auth
        localStorage.setItem('checkoutAfterAuth', 'true');
        window.location.href = '/signup';
    } else {
        continueToCheckout();
    }
}
```

### Step 4: Update Cart Owner After Authentication

Once the user completes authentication, update the Cart's Owner from the session ID to the authenticated user ID.

```javascript
// Backend: After successful signup/login
app.post('/api/auth/login', async (req, res) => {
    // ... authentication logic ...

    const user = authenticatedUser;
    const cartId = req.body.cartId; // Passed from frontend

    if (cartId) {
        try {
            await updateCartOwner(cartId, user.id);
        } catch (error) {
            console.error('Failed to transfer Cart:', error);
            // Cart transfer failing shouldn't block login
        }
    }

    res.json({ user, success: true });
});
```

### Step 5: Continue to Checkout

With the Cart now linked to the authenticated user, proceed to generate the checkout URL.

```javascript
// Frontend: After login redirect
if (localStorage.getItem('checkoutAfterAuth') === 'true') {
    localStorage.removeItem('checkoutAfterAuth');
    continueToCheckout();
}
```

## Generating Checkout URLs

### API: Generate Checkout Link

**Endpoint:** `POST /api/carts/{cartId}/checkout`

Generate a Stripe Checkout session URL for customers to complete payment.

**Request Body:**

```json
{
    "successUrl": "https://yourapp.com/welcome",
    "cancelUrl": "https://yourapp.com/pricing",
    "email": "customer@example.com",
    "allowPromoCodes": true,
    "automaticTax": false,
    "collectBillingAddress": true,
    "collectShippingAddress": false,
    "cardPrefillPreference": "choice",
    "trialPeriodDays": 14
}
```

**Parameters:**

These parameters can be provided in the API call or configured in your Product settings. If a value exists in the Product settings, it will be used as the default. Providing a value in the API call overrides the Product settings.

**Required (unless configured in Product settings):**

- **successUrl** - URL where Stripe redirects customers after successful payment
- **cancelUrl** - URL where customers return if they abandon checkout

If multiple Products in your Cart have conflicting URL defaults, you must provide explicit values in the API call.

**Optional:**

- **email** - Pre-fills the customer email in the checkout form
- **allowPromoCodes** - Enables promotional code entry at checkout (boolean)
- **automaticTax** - Enables Stripe Tax for automatic tax calculation (boolean)
- **collectBillingAddress** - Requires billing address at checkout (boolean)
- **collectShippingAddress** - Requires shipping address at checkout (boolean)
- **cardPrefillPreference** - Controls saving payment methods: `none`, `choice`, or `always`
- **trialPeriodDays** - Number of days for trial period before billing begins (1-730 days)

**Response:**

```json
{
    "data": {
        "url": "https://checkout.stripe.com/c/pay/cs_live_..."
    }
}
```

### Checkout Implementation

```javascript
async function generateCheckoutUrl(cartId, email, successUrl, cancelUrl) {
    const response = await fetch(`https://api.salable.app/api/carts/${cartId}/checkout`, {
        method: 'POST',
        headers: {
            Authorization: `Bearer ${process.env.SALABLE_SECRET_KEY}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            email,
            successUrl,
            cancelUrl,
            allowPromoCodes: true,
            collectBillingAddress: true,
            cardPrefillPreference: 'choice'
        })
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.title);
    }

    const { data } = await response.json();
    return data.url;
}

// Example: Handle checkout button
app.post('/api/cart/:cartId/checkout', async (req, res) => {
    try {
        const checkoutUrl = await generateCheckoutUrl(
            req.params.cartId,
            req.user.email,
            `${process.env.APP_URL}/welcome`,
            `${process.env.APP_URL}/pricing`
        );

        res.json({ checkoutUrl });
    } catch (error) {
        res.status(400).json({ error: error.message });
    }
});
```

### Checkout Behavior

When you generate a checkout URL, Salable performs several operations behind the scenes. It creates or updates Grantee Groups based on the Cart items. For Cart items without a Grantee Group ID, a new Grantee Group is created. If a Grantee ID was provided, it adds that Grantee to the new Grantee Group. For per-seat Line Items without a Grantee, it creates an empty Grantee Group that can be populated later.

The Cart status changes to **complete** after successful payment, preventing any further modifications. Once Stripe confirms the payment is successful Salable creates a Subscription, Subscription Plan records, and usage tracking for metered items in your organization.

## Best Practices

### Session Management for Anonymous Carts

Use a consistent session identifier throughout the anonymous user's journey. Store the Cart ID in localStorage or a cookie so it persists across page refreshes. When the user authenticates, make sure to transfer the Cart Ownership immediately to prevent losing their selections.

### Currency Selection Strategy

Choose the currency approach that best fits your business model and customer experience.

**Explicitly defining currency** is recommended when you know the customer's currency context. Detect the customer's location or preferences in your application, display your pricing page in that currency, and then create the Cart with that currency explicitly set. This approach provides several benefits: it ensures customers see consistent pricing from your pricing page through to Stripe checkout, preventing confusion from unexpected currency changes, and it gives you greater flexibility when designing your pricing models. With an explicit currency, you can implement region-specific pricing strategies—like offering discounts in emerging markets, adjusting for purchasing power parity, or experimenting with different price points in different currencies—without needing to configure every currency option across every Line Item.

You can use various methods to determine currency: detect the customer's location using their IP address with a geolocation service, allow customers to select their preferred currency from your pricing page, use the customer's browser locale or account settings, or default to your primary market currency. Once you know the currency, provide it explicitly when creating the Cart.

**Omitting currency** is a valid option when you want Stripe to handle currency detection automatically at checkout. This works well if you're displaying prices generically (without showing specific currency symbols or amounts) or if you're comfortable with Stripe determining the best currency for each customer. However, be aware that the currency shown at checkout may differ from what the customer saw on your pricing page if you displayed prices in a specific currency. This can lead to customer confusion or surprise when they encounter different pricing than expected.

**Key consideration**: When omitting currency, all Line Items across all Plans in your Product must have the same default currency configured. You can have prices in multiple currencies (USD, GBP, EUR, etc.), but one must be marked as default, and that default must be consistent across all Line Items. If you have Products with different default currencies, you must provide an explicit currency when creating Carts that include Plans from multiple Products.

### Validation Before Checkout

Before generating a checkout URL, validate that the Cart has at least one item and that all quantities are within acceptable ranges. This prevents errors during the Stripe checkout session creation.

### Multiple Plans in One Purchase

Let customers add multiple Plans to their Cart in a single purchase. This is convenient for base Subscriptions plus add-ons, or for purchasing access to multiple Products simultaneously. Each Plan can have different Line Items and pricing structures, and Salable handles the complexity of creating a single checkout.

> **Important**: Each Plan can only be added to the Cart once. Attempting to add the same Plan multiple times will fail. If you need multiple quantities of an item, use the quantity parameter on the Line Item instead.

### Handling Checkout Failures

Not all checkout sessions result in completed payments. Customers might abandon the Stripe checkout page, their payment might fail, or they might close the browser. Keep Carts in **active** status until you receive webhook confirmation of successful payment. This lets customers return to their Cart and try checking out again.

## Troubleshooting

### Cart Creation Fails with 400 Error

If Cart creation fails with a 400 error, check that the currency code is valid and recognized by Stripe. Common valid codes include USD, GBP, EUR, CAD, AUD, and many others. The currency must be supported by your Stripe account's configuration.

### Cannot Add Item: Plan Already in Cart

Each Plan can only be added to a Cart once. If you need different configurations of the same Plan (like different seat counts), you'll need to use different Plans rather than adding the same Plan multiple times. Alternatively, update the Cart item's metadata with the new quantities rather than adding a duplicate.

### Cannot Add Item: Invalid Metadata for Metered Line Item

If you include a metered Line Item in your Cart item metadata, the request will fail with an error. Metered Line Items track usage after Subscription creation and should never be included in the metadata object. Only include non-metered Line Items where you need to set quantities above their configured minimum.

### Cannot Add Item: Owner Already Subscribed to Metered Item

If you try to add a metered Line Item to a Cart and the Owner already has an active Subscription with that same meter slug, the request will fail. This prevents duplicate usage tracking which would cause billing issues. To resolve this, the customer would need to either cancel their existing Subscription with that meter or choose a different Plan.

### Checkout Link Generation Fails: Missing URLs

If you don't provide `successUrl` and `cancelUrl` in the checkout request and the Plans in the Cart don't have Product-level defaults configured, the request will fail. Always either configure these URLs in your Product settings or provide them explicitly in the checkout API call.

### Checkout Link Generation Fails: No Payment Integration or Missing Business Information

If checkout link generation fails with an error along the lines of "In order to use Checkout, you must set an account or business name," this indicates that your Stripe account is missing required information.

**For Test Mode:**
You must complete both the **business type** form and the **personal details** form in Stripe's onboarding. Navigate to Payment Integrations in your dashboard, access your Stripe Connect settings, and complete both required forms. You don't need to complete full onboarding (banking, identity verification) for test mode checkout links.

**For Live Mode:**
You must have a fully onboarded Stripe account with **Active** status. This includes business information, banking details, and identity verification. Navigate to Payment Integrations to check your onboarding status and complete any pending requirements.

### Checkout Link Generation Fails: Currency Default Mismatch

If you created a Cart without specifying a currency and checkout fails with a Stripe error about currencies, this means the Line Items in your Cart have different default currencies. For example, one Plan's Line Items might default to USD while another Plan's Line Items default to GBP.

To resolve this, either configure all your Line Items to use the same default currency, or create the Cart with an explicit currency that all Line Items support. When using explicit currency, Salable will cherry-pick only the Line Items with that currency, avoiding the conflict.

### One-Off Items Not Appearing in Cart

If your one-off Line Items aren't being included when you add a Plan to the Cart, check the currency configuration. One-off Line Items are automatically included regardless of the Cart's interval, but they still need to have pricing configured in the Cart's currency. If the Cart has an explicit currency set, ensure your one-off Line Items have a Price in that currency. And, if using cart geolocation for the currency, ensure the default currency of any one-off line items match the default currency of all other items in the cart.

## Summary

Salable's Cart system provides a flexible foundation for building checkout experiences. Create Carts for both anonymous and authenticated users, add multiple Plans with custom quantities, and generate Stripe Checkout sessions with a single API call. The system handles Owner management automatically, validates quantities and compatibility, and creates all necessary grantee groups during the checkout process.

The Cart system supports both recurring subscriptions and one-off purchases. For recurring billing, specify an interval like `month` or `year`. For one-off purchases, set `interval` and `intervalCount` to `null`. Plans can combine both one-off and recurring Line Items, Salable automatically includes one-off items regardless of the Cart's interval.

Choose between explicit currency selection for precise control or geolocation-based pricing to automatically show customers prices in their local currency. The anonymous-to-authenticated flow makes it easy to reduce friction in your signup process, letting users explore and configure their purchase before committing to creating an account. With support for multiple Plans, flexible pricing configurations, one-off and recurring billing, and automatic validation, you can build sophisticated checkout flows without managing the underlying complexity.
