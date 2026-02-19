---
title: 'The Cart System: Core Products with Add-Ons Done Right'
description: 'Traditional billing forces a choice between fragmented subscriptions or monolithic bundles. The cart system lets customers build their own bundle from your product catalogue.'
publishedAt: 2026-02-10
category: Beta Features
author: sean-cooper
tags:
    - cart
    - checkout
    - features
    - billing
draft: false
featured: false
---

# The Cart System: Core Products with Add-Ons Done Right

<!-- IMAGE: Shopping cart interface showing core product plus multiple add-ons
     Placement: hero
     Suggested: Checkout flow with bundled items displayed clearly -->

Your customer wants your Professional plan plus the Analytics add-on, the API Access module, and maybe the White Label extension. Traditional billing systems force a choice: separate subscriptions that fragment the customer relationship, or a monolithic plan that bundles everything whether customers want it or not. Neither works. Salable's cart system solves this by letting customers purchase multiple plans as a single subscription. The core product and add-ons live together, billed together, managed together. And when needs change, customers can add new capabilities, remove what they don't use, or replace one add-on with another, all without creating subscription chaos.

The problem with separate subscriptions goes beyond administrative inconvenience. Each subscription is an independent relationship with its own lifecycle. Different renewal dates mean staggered billing that confuses customers. Cancelling the core product doesn't automatically cancel add-ons, leading to surprised complaints when charges continue. Cross-product entitlements become complicated when the systems aren't connected. You end up building integration logic between your own subscriptions.

Monolithic bundles avoid these problems but create new ones. If the Analytics add-on and the API Access module are bundled into your Professional plan, customers who want only one must pay for both. Those who need neither but want the core Professional features are subsidising capabilities they don't use. Unbundling means creating more plans, which means a more complex pricing page and harder purchasing decisions for customers.

The cart model lets you bundle without bundling. Products and add-ons remain separate for pricing and entitlement purposes, but they combine into a single subscription for billing and lifecycle management. Customers build their own bundle from your menu of options.

## How Carts Create Composable Subscriptions

A cart in Salable works like a shopping cart in e-commerce, but for subscription products. Customers add plans to their cart, and when they check out, all the plans become line items in a single subscription.

The subscription that results has a unified billing cycle. All line items renew together. The customer sees one charge on their credit card statement, not separate charges for each component. If they view their subscription in your customer portal, they see everything they've purchased as parts of a whole.

<!-- IMAGE: Subscription detail showing multiple line items from different plans
     Placement: inline
     Suggested: Customer portal view of a composed subscription -->

Entitlements from all the plans in the subscription apply to the customer. If the Professional plan includes project management features and the Analytics add-on includes dashboard features, the customer has access to both. Your entitlement checks don't need to know about the cart structure; they just check whether the customer's subscription includes the relevant entitlement.

This composition is flexible at purchase time but coherent after purchase. The customer chooses what they want; once subscribed, it behaves as a single unit.

## Designing for Cart-Based Purchasing

Thinking in terms of carts changes how you structure your pricing. Instead of comprehensive plans that try to serve all customers, you design a core product and a catalogue of add-ons.

The core product should provide standalone value. It's what most customers need and what defines your product's primary use case. Everything else becomes optional add-ons that extend, enhance, or specialise the core functionality.

Add-ons typically fall into a few categories. Feature extensions add capabilities beyond the core product, like advanced analytics, API access, or white-label options. Capacity extensions increase limits, like additional storage, more users, or higher API rate limits. Professional services like priority support, dedicated account management, or custom training can also be add-ons rather than bundled into premium tiers.

The key principle is that add-ons should provide independent value. A customer who buys the Analytics add-on should receive clear benefit from it regardless of whether they also buy the API Access module. If two add-ons only make sense together, consider combining them into a single add-on or making one dependent on the other.

## The Checkout Experience

Cart-based checkout needs UI that supports browsing and selection. Unlike single-product checkout where the customer clicks a plan and enters payment details, cart checkout involves building a bundle before payment.

Your pricing page becomes more of a product catalogue. Each option shows what it provides and what it costs. Customers can select their core plan and then browse available add-ons, toggling them into their cart as they go.

<!-- IMAGE: Pricing page with selectable core plans and toggleable add-ons
     Placement: inline
     Suggested: Interactive pricing UI showing cart building -->

The cart summary should be visible throughout the selection process. Customers need to see their running total and the list of what they've selected. Changes to the cart update the summary immediately, so there are no surprises at checkout.

For simple product catalogues, an accordion or toggle interface works well. Core plans show prominently, add-ons appear as checkboxes or toggles beneath them, and the selected items stack in a sidebar cart. For more complex catalogues, a dedicated cart page where customers review and adjust their selections before proceeding to payment might be clearer.

The checkout itself collects payment information and processes the composed cart as a single subscription. Salable handles the cart-to-subscription conversion, creating the unified subscription with all selected line items. The customer's payment method is charged for the combined total.

## Modifying Subscriptions After Purchase

One advantage of the cart model is that subscriptions can be modified without wholesale replacement. Customers can add new add-ons to an existing subscription, remove add-ons they no longer need, or replace one add-on with another.

Adding an add-on to an existing subscription happens immediately—no cart required. The customer selects the new add-on, and the subscription updates to include it. Their payment method is already on file, so billing prorates automatically, charging for the remainder of the current billing period without requiring another checkout flow.

Removing an add-on follows a similar flow but in reverse. The customer indicates they want to remove something, and the subscription adjusts. Depending on your policies, the removal might be immediate or take effect at the next renewal. Credits for unused time can apply or not based on how you've configured the add-on.

Replacing one add-on with another, such as swapping a standard support add-on for a premium support add-on, combines removal and addition in a single operation. The customer sees this as an upgrade or change rather than two separate transactions.

## Managing Complex Bundles

Some products have interdependencies between add-ons. The API Access module might require the Professional plan or above. The White Label extension might be incompatible with certain integrations. Your checkout flow needs to handle these constraints.

Implement availability logic in your pricing page and checkout UI. When a customer selects a core plan, show only the add-ons compatible with that plan. Hide or disable options that don't apply, with explanations where helpful. This filtering happens in your application before the cart reaches Salable, ensuring customers only see valid combinations.

For complex dependency trees, document the relationships clearly for customers. A diagram showing which add-ons work with which plans, or a guided selection flow that filters options based on prior selections, helps customers navigate without frustration.

## Billing and Revenue Recognition

Cart-based subscriptions consolidate billing but still provide line-item visibility for accounting and analysis.

Invoices show each plan in the subscription as a separate line item. The Professional plan is \$99, the Analytics add-on is \$29, the API Access module is \$49; the total charge is \$177. This breakdown helps customers understand their charges and simplifies expense allocation for businesses that track costs by category.

<!-- IMAGE: Invoice showing itemized breakdown of cart-purchased subscription
     Placement: inline
     Suggested: Sample invoice with multiple line items from cart purchase -->

For your revenue reporting, you can see performance at the line item level. Which add-ons are most popular? What's the average add-on revenue per subscription? Which combinations drive the highest lifetime value? This granularity helps you optimise your product catalogue and pricing.

Revenue recognition treats the subscription as a unit but can segment by line item if needed. The total monthly recurring revenue from a cart-purchased subscription attributes appropriately across the components that comprise it.

## The Strategic Advantage

Cart-based purchasing isn't just operational convenience; it's a strategic advantage in how you monetise and grow.

Modularity lets you serve more customer segments without proliferating plans. Instead of Starter, Professional, Professional Plus, Professional Plus with Analytics, and Professional Enterprise bundles, you have a core product and a menu. Customers build what they need; you don't need to anticipate every combination.

Expansion revenue becomes natural. When a customer needs more capability, they add an add-on. This is lower friction than upgrading to a higher tier plan that includes capabilities they didn't ask for. The upsell conversation is "would you like this specific thing?" rather than "would you like to pay more for a bigger package?"

Churn reduction comes from precise fit. Customers who have exactly what they need are less likely to leave than customers paying for capabilities they don't use. The subscription matches their requirements rather than approximating them.

Testing new products becomes simpler. Launch a new add-on, make it available in the cart, see who buys it. If it succeeds, keep it. If it doesn't, remove it. The cart architecture supports experimentation without restructuring your core offering.

## Building for Carts

Implementing cart-based purchasing requires changes across your pricing page, checkout flow, customer portal, and entitlement logic. The scope is significant but the components are well-defined.

Your pricing page needs to support selection and cart building. This is primarily a frontend concern: displaying options, tracking selections, showing the running total, and passing the cart to checkout.

Your checkout flow needs to accept a cart and create a composed subscription. Salable's checkout handles this, receiving the cart items and processing them into a single subscription. You pass the cart contents; the system handles the rest.

Your customer portal needs to show the subscription composition and support modifications. Customers should see what's in their subscription, what add-ons are available, and have clear paths to add or remove items.

Your entitlement logic doesn't need to change if it's already checking subscription entitlements. The entitlements from all cart items combine in the subscription, so standard entitlement checks work without modification.

The cart system transforms your billing from a constraint into an enabler. Customers get exactly what they need. You capture revenue from every capability they value. And the subscription relationship remains unified, simple to manage, easy to understand, and straightforward to modify as needs evolve.

Your Professional plan plus Analytics plus API Access plus White Label becomes one subscription, one invoice, one relationship. That's what add-ons done right looks like.
