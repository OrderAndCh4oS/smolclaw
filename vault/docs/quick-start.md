---
description: Get your first subscription up and running in around ten minutes. This guide walks you through setting up a payment integration, creating a product, adding a plan, completing a checkout, and performing an entitlement check. All you need is a Salable account and a few minutes to see the full subscription flow in action.
---

# Salable Quick Start Guide

## Step 1: Enable Test Mode

Toggle **[Test Mode](/docs/core-concepts#test-mode-vs-live-mode)** on using the switch at the bottom left. While we're in Test Mode, anything we create throughout this guide will be strictly test data.

## Step 2: Create and Set Up a Payment Integration

In Salable, **Payment Integrations** allow us to accept payments for our Products and are powered by Stripe.

Click the Payment Integrations tab in your sidebar and click the Create Payment Integration button. You will be taken to the Stripe Connect onboarding flow. After completing the onboarding process, you will be redirected back to Salable.

> **Note** For this guide, you will only have to complete the Business Type form and the Personal Details section. To take live payments, you would also need to enter your banking details and verify your identity as instructed throughout the onboarding process.

## Step 3: Create a Product

A **[Product](/docs/core-concepts#product)** on Salable contains your pricing model, Plans, and features. Click on the Products tab on the sidebar to navigate to the Products page. Provide a name for your Product in the Product Name field (_eg_ "My SaaS Product") and click the Create Product button.

## Step 4: Create a Plan

**[Plans](/docs/core-concepts#plan)** allow you to define a payment model and the Entitlements you want to make available for it.

Click the Manage Product button (pencil icon) on your Product.

Provide a name for your Plan (_eg_ "Basic Plan") on the Plan Name field and click the Create Plan button.

## Step 5: Create an Entitlement

**[Entitlements](/docs/core-concepts#entitlement)** grant access to features (_eg_ `export_pdf`, `generate_images`) in your Product. When a user subscribes to a Plan, they receive these Entitlements.

To create an Entitlement, locate the Select Entitlements form field. Enter `entitlement_one` for your Entitlement name and click the (+) button to create and add the Entitlement to your Plan.

## Step 6: Create a Line Item

**[Line Items](/docs/core-concepts#line-item)** are the individual pricing components that constitute the overall payment model of your Plan. There are several types of Line Items, each with its own pricing structure. For this guide, we will create a **Flat Rate** Line Item that charges a fixed fee each billing cycle.

Click the Add Line Item button to pull up the Line Item form.

Provide a name for your Line Item in the Line Item Name field (_eg_ Monthly Subscription Fee). This is the name that will appear on Stripe invoices, so be sure to name your Line Items accordingly.

We will leave the Interval Type set to Recurring and the Price Type set to Flat Rate.

Next, we will set up a **[Price](/docs/core-concepts#price)**, set the Currency to USD, and set the Unit Amount to \$4.99. We will leave Interval set to Month and Interval Count set to one.

Click the Save Plan button to provide your Plan with your new Line Item.

## Step 7: Generate a Checkout Link

So far, we have set up a Payment Integration, created a Product, created a Plan, and assigned an Entitlement and a Line Item to the Plan. Now, let's purchase a **[Subscription](/docs/core-concepts#subscription)**.

Scroll below the Plan form to find another form that lets you add your Plan to your **[Cart](/docs/core-concepts#cart)**.

Select USD for the currency, month for the interval, and set the interval count to 1.

You will see two fields: Owner and Grantee. The **[Owner](/docs/core-concepts#owner)** should be an ID in your system that can be used to look up and manage the Subscription. The **[Grantee](/docs/core-concepts#grantee)** represents the entity that will be granted access to features in your application. Typically, the Grantee is a user ID. However, it could also be an organisation, team or any other entity ID ([Read more about Owners and Grantees here](/docs/core-concepts#access-control)).

Enter `owner_one_id` for the Owner field and click the (+) button, then enter `grantee_one_id` for the Grantee field.

Click the Add to Cart button and click Go to Cart to navigate to the Manage Cart page.

From here, you can review the contents of your Cart. When you're ready to proceed with the purchase, click the Checkout Cart button to begin **[Checkout](/docs/core-concepts#checkout)**.

## Step 8: Complete Test Checkout

On Stripe’s checkout page, enter the following test payment details:

- Email Address `someone@example.com`
- Card number: `4242 4242 4242 4242`
- Expiry: Any future date
- CVC: Any 3 digits
- Postal code/Zip code: Any code

> **Note** The actual fields may vary depending on your region

Click Subscribe to complete the checkout.

## Step 9: Verify Your Subscription

You'll be redirected to Salable and taken to the Subscriptions page. You should see your newly created Subscription with the Active status.

If you click on the Subscription to view details, you'll see:

- The Owner
- The associated Plan
- A list of **[Invoices](/docs/core-concepts#invoice)**, including a draft of the next Invoice

## Step 10: Check Entitlement Access

Let's perform an Entitlement Check with your newly created Subscription and Grantee to confirm they have access to the Entitlement.

- Navigate to the Entitlement Check tab
- In the Grantee ID field, enter `grantee_one_id`
- Click Check Grantee

You should see the following response:

```json
{
    "type": "object",
    "data": {
        "entitlements": [
            {
                "value": "entitlement_one",
                "type": "entitlement",
                "expiryDate": "2026-01-02T17:28:41.000Z"
            }
        ],
        "signature": "3045022054188fb22b12a9e8565beda67a9859a7e3eb23e31f806a1dccf7b551267e46b9022100b29021c7b579e36a63d6b1b6c1e2be55c64a285a15223119ab1b17f88410047b"
    }
}
```

This confirms that your Grantee has access to the Entitlement we created earlier.

## Conclusion

You have successfully:

- Created and onboarded a Payment Integration
- Created a Product
- Created a Plan
- Created an Entitlement
- Created a Line Item with a price, currency, and billing interval
- Successfully purchased a Subscription
- Performed an Entitlement Check on a Grantee

You are now familiar with the core concepts of Salable!

Still have questions? [Click here to review core concepts](/docs/core-concepts).
