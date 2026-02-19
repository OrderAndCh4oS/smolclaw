---
title: 'Introducing Tiered Pricing: Volume Discounts Made Simple'
description: 'Stop managing volume discounts in spreadsheets. Learn how tiered pricing automates discount calculations, the difference between graduated and volume tiers, and how to design tier structures that reward growth.'
publishedAt: 2026-01-27
category: Beta Features
author: sean-cooper
tags:
    - pricing
    - tiered-pricing
    - features
    - billing
draft: false
featured: false
---

Every growing SaaS hits the same wall: your biggest customers want volume discounts, but your billing system only supports one price per unit. You end up with spreadsheets tracking custom deals, manual invoice adjustments, and a pricing page that lies to your best customers. Tiered pricing solves this by encoding volume discounts directly into your pricing model. Buy more, pay less per unit, automatically calculated and invoiced without human intervention.

The request usually comes from a sales call. A prospect loves your product and wants to roll it out across their organisation, but they balk at paying the same per-user rate for 500 seats that they'd pay for five. You want to accommodate them because larger deals mean better unit economics for you too. But your billing system doesn't support volume discounts, so you create a custom plan, track it in a spreadsheet, and hope you remember to honour the special pricing when the invoice goes out.

This approach doesn't scale. By the time you have a dozen custom deals, you're spending hours each month reconciling billing against your spreadsheet of promises. Worse, you can't publish volume discounts on your pricing page because your system can't calculate them automatically. Potential customers who would self-serve at higher volumes never see that option.

Tiered pricing automates what you're already doing manually. You define price brackets based on quantity, and the billing system calculates the correct charge for any order size. A customer buying 10 units pays one rate; a customer buying 100 units pays a lower rate per unit; a customer buying 1,000 units pays lower still. No spreadsheets, no manual adjustments, no special deals that slip through the cracks.

## How Tiered Pricing Works

The fundamental concept is straightforward: you divide quantities into brackets, and each bracket has its own unit price. When a customer's usage or purchase quantity falls into a bracket, that bracket's pricing applies. The complexity lies in _how_ the pricing applies, which brings us to the critical distinction between graduated and volume tiers.

Understanding this distinction matters because choosing the wrong model can either leave money on the table or create pricing cliffs that confuse customers. The names sound similar, but they produce dramatically different invoices.

With **graduated tiers**, each bracket charges its own rate for the units within that bracket. Think of it like income tax brackets in many countries. If your first tier covers units one through 50 at $10 each, and your second tier covers units 51 through 100 at $8 each, a customer buying 75 units pays $10 for the first 50 units plus $8 for the next 25 units, totalling $700.

With **volume tiers**, the qualifying bracket applies to _all_ units. Using the same brackets, a customer buying 75 units falls into the second tier, so they pay $8 for all 75 units, totalling $600. The per-unit rate they qualify for applies universally rather than bracket by bracket.

The mathematical difference is significant. In the graduated example, the customer pays $700. In the volume example, they pay $600. That's a 14% difference from the same tier structure, just applied differently.

## Choosing Between Graduated and Volume Tiers

Graduated tiers suit most SaaS pricing scenarios because they create smooth cost curves. As customers grow, their costs increase proportionally with a gentle downward slope in per-unit pricing. There are no sudden jumps or counterintuitive moments where buying more actually costs less.

Volume tiers create discount cliffs, which can be strategically useful but require careful design. Consider what happens at tier boundaries with volume pricing. If units one through 100 cost $10 each and units 101 through 200 cost $8 each, a customer buying 100 units pays $1,000, but a customer buying 101 units pays $808. Buying one more unit saves them $192. This cliff effect can drive behaviour you want, like pushing customers to commit to higher volumes, but it can also create support headaches when customers game the system or feel tricked.

The general guidance is to default to graduated tiers unless you have a specific reason to create discount cliffs. Graduated tiers are easier to explain, less prone to edge-case confusion, and still reward volume purchases without the counterintuitive pricing moments.

## Designing Your Tier Structure

The number of tiers and where you set the boundaries depends on your customer distribution and business goals. Too few tiers and you're not rewarding volume growth. Too many tiers and your pricing page becomes unreadable.

Most successful tiered pricing implementations use three to five brackets. The first tier covers your typical individual or small team customer. The middle tiers capture growing businesses. The top tier, often labelled "Enterprise" or with custom pricing, handles your largest accounts.

Setting boundaries requires looking at your actual customer data. Where do customers naturally cluster? If most customers have between one and ten users, but you have a meaningful segment with 50 to 200 users, and occasional accounts with 500 or more, your tier boundaries might fall at 10, 50, 200, and 500+ units.

The discount progression matters too. A 5% discount per tier feels minimal; customers might not notice it. A 50% discount per tier might be unsustainable for your margins. Most tiered pricing lands somewhere between 10% and 25% discount per tier, with larger jumps at higher volumes where your marginal costs are genuinely lower.

## Implementation Without the Headaches

The promise of tiered pricing is automation. You configure your tiers once, and every invoice calculates correctly regardless of customer size. But achieving this automation requires a billing system that supports tiered pricing natively.

In Salable, you configure tiered pricing directly on your line items. You define each tier with its quantity range and unit price, choose between graduated and volume calculation, and the system handles everything else. When a customer's subscription renews or their metered usage gets invoiced, the tier calculation happens automatically. If they grow from 75 seats to 150 seats mid-cycle, the invoice prorates correctly across the applicable tiers.

This native support matters because retrofitting tiered pricing onto a system that doesn't support it creates fragile workarounds. You end up with webhook handlers that intercept invoices and recalculate totals, or duplicate products that represent different volume levels. These workarounds break when Stripe changes their API or when you need to handle edge cases like mid-cycle upgrades.

## Communicating Tiered Pricing to Customers

Automated calculation only helps if customers understand what they're being charged. Tiered pricing can confuse buyers who expect a single unit price, so your pricing page and checkout flow need to explain the model clearly.

The most effective approach shows both the per-unit price at each tier and a calculated example at common quantities. A table showing your tier brackets gives customers the raw information, while calculated examples like "50 users: $400/month" and "200 users: $1,200/month" make the savings tangible.

For self-serve checkout, showing the calculated total based on the quantity they've entered removes uncertainty. The customer selects 75 seats, and the checkout shows them exactly what they'll pay, broken down by tier if you're using graduated pricing. No surprises on the invoice.

For sales-assisted deals, tiered pricing gives your sales team a framework for volume discounts that doesn't require manager approval for every deal. The customer qualifies for the published tier, period. This consistency builds trust and speeds up the sales cycle.

## When Tiered Pricing Isn't the Answer

Tiered pricing works best when you're selling countable units at predictable volumes. Per-seat licensing, API calls, storage gigabytes, and similar metrics fit the model naturally. But not every pricing situation calls for tiers.

If your value delivery is genuinely flat regardless of usage, tiers add complexity without benefit. A product that costs the same to serve whether the customer has one user or a hundred might be better priced as a flat monthly fee with an upper limit.

If customer value varies dramatically by use case rather than volume, you might need separate products rather than volume tiers. A customer processing financial transactions and a customer tracking inventory might both use your API, but the value you deliver differs enough that volume alone doesn't capture it.

And if your largest customers need genuinely custom arrangements involving SLAs, dedicated infrastructure, and bespoke integrations, those belong in enterprise sales conversations rather than self-serve tiered pricing. Tiers work for automated volume discounts; they don't replace relationship-driven enterprise deals.

## Moving Forward with Tiered Pricing

The path from manual volume discounts to automated tiered pricing starts with understanding your current customer distribution. Look at how many customers you have at each volume level, what discounts you're already offering informally, and where the natural breakpoints fall.

Design your tier structure around that data, defaulting to graduated tiers unless you have a specific reason to create volume discount cliffs. Keep the number of tiers manageable, typically three to five, with meaningful discounts that reward growth without destroying your margins.

Implement the tiers in a billing system that supports them natively rather than bolting on workarounds. Test the calculation at boundary conditions, especially at tier edges and with mid-cycle changes.

Finally, communicate the pricing clearly to customers. Show the tier structure, provide calculated examples, and display real-time totals at checkout. Tiered pricing should feel like a reward for volume, not a puzzle to solve.

The spreadsheets tracking your custom deals can finally go away. Your pricing page can tell the truth to every customer, including your biggest ones. And your billing system can handle the math that you've been doing manually, automatically and correctly, for every invoice going forward.
