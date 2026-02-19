---
title: 'The Entitlements Pattern: Feature Gating That Actually Works'
description: "Stop checking which plan users are on. Check what they're allowed to do instead. Plans grant capabilities, capabilities gate features, and your pricing can evolve without touching code."
publishedAt: 2026-03-17
category: SaaS Startup Guides
author: sean-cooper
tags:
    - entitlements
    - architecture
    - saas
    - features
draft: false
featured: false
---

# The Entitlements Pattern: Feature Gating That Actually Works

You've shipped your app with tier-based access controls, and it works. Users on the Pro plan get Pro features, Enterprise users get everything. Then your pricing changes. You add a tier, rename a plan, or close a deal that doesn't fit your standard packages—and suddenly you're hunting through your codebase, updating hardcoded plan names, hoping you haven't locked a paying customer out of something they bought.

The entitlements pattern prevents this entirely. Instead of checking which plan a user is on, your code checks what they're allowed to do. Plans grant capabilities, capabilities gate features, and the mapping lives in configuration. Your pricing can evolve without your codebase knowing or caring.

<!-- IMAGE: Two code snippets side by side - brittle tier check vs clean entitlement check
     Placement: hero
     Suggested: Code comparison illustration, showing cleaner approach -->

## The Problem with Tier-Based Checks

Most developers start with tier-based access control because it's intuitive. You have plans called "Starter," "Pro," and "Enterprise," so your code checks which plan a user is on. The logic seems straightforward: Pro users get advanced features, Enterprise users get everything.

The problems emerge slowly, then all at once.

First, the checks multiply. Feature gating code starts in one or two files, then spreads throughout your codebase as you add more premium features. Your advanced analytics component checks the tier. Your export functionality checks the tier. Your API rate limiter checks the tier. Your admin panel checks the tier. Each check is trivial in isolation, but together they form a scattered, implicit definition of what each plan includes.

Second, the tiers change. You decide that "Pro" is too expensive and split it into "Pro" and "Pro Plus." Or you rename "Starter" to "Essential" for marketing reasons. Or you add a "Growth" tier between existing tiers. Each change requires finding and updating every tier check in your codebase. Miss one, and you've either given away features for free or locked paying customers out of functionality they purchased.

Third, customers don't fit your tiers. A startup wants the analytics from Pro but only needs the user limits from Starter—and they want a price that reflects the mix. An enterprise customer needs one specific feature from your top tier but nothing else that justifies the cost. When your code assumes every customer maps to exactly one tier, these deals become engineering problems. You end up hardcoding exceptions by customer ID or creating fake tiers that exist only to satisfy one contract.

The tier-based approach implicitly assumes your pricing structure is stable and your feature sets map cleanly to tiers. Neither assumption holds for long.

## Capabilities Over Tiers

The entitlements pattern inverts the relationship between plans and features. Instead of asking "what plan is this user on?" your code asks "does this user have this capability?" The plan determines which capabilities a user has, but plan names never appear in your feature code.

Consider an export feature. With tier-based checks, your code might look like this:

```javascript
if (user.plan === 'pro' || user.plan === 'enterprise') {
    showExportButton();
}
```

With entitlements, it becomes:

```javascript
if (user.hasEntitlement('export_data')) {
    showExportButton();
}
```

The difference seems cosmetic, but it's architecturally significant. The first approach embeds your pricing structure into your codebase. The second decouples them entirely. Plans grant entitlements, and entitlements control features, but your feature code only references entitlements.

<!-- IMAGE: Diagram showing Plan -> Entitlements -> Features flow
     Placement: diagram
     Suggested: Clean architectural diagram with clear arrows -->

This separation lets you restructure pricing without touching feature code. Want to split Pro into two tiers? Update the entitlement mappings. Want to offer a custom bundle? Create a plan with the right entitlements. Want to run a promotion that gives Starter users temporary access to Pro features? Grant the entitlements temporarily. Your feature code stays exactly as it was.

## Designing Your Entitlement Vocabulary

The power of entitlements depends on choosing the right granularity. Too coarse, and you lose flexibility; too fine, and you're back to scattering checks everywhere, just with different names.

Start by listing everything you might want to gate. This includes features, usage limits, support tiers, and integrations. Don't worry about which plan gets what yet; just identify the decision points in your product.

Next, look for natural groupings. Some capabilities always go together. If every plan that gets "export_csv" also gets "export_json," you might combine them into "export_data." If "advanced_charts" and "custom_dashboards" always travel together, consider "advanced_analytics."

Name entitlements for what they enable, not which plan includes them. "export_data" is better than "pro_export" because the name survives pricing changes. "unlimited_projects" is better than "enterprise_tier" because it describes a capability, not a position in your pricing hierarchy.

Consider both boolean entitlements and quantitative ones. Some capabilities are yes-or-no questions: can this user export data? Others are limits: how many projects can this user create? The entitlements pattern handles both, but they work differently in practice.

Boolean entitlements are straightforward. The user either has the capability or doesn't. Your code checks once and proceeds accordingly.

## Implementing Entitlements with Salable

Salable handles the complexity of entitlement resolution so you don't have to build it yourself. You define your plans and their capabilities in the Salable dashboard, then check entitlements with a single API call.

Entitlement checks are performed on a granteeId—typically your user ID. When you need to know what someone can do, you ask Salable for that grantee's entitlements. If the user belongs to multiple owners (say, a personal account and an enterprise organisation), you filter by owner to get the entitlements for the tenant they're currently operating in. The response collates everything for that context—base plan, add-ons, custom deals—into one list of capabilities.

This means your application never needs to understand your pricing structure. It doesn't know what plans exist, how much they cost, or which features belong to which tier. It just knows capabilities. When you restructure pricing, add plans, or close custom deals, your application keeps working without changes.

<!-- IMAGE: Code architecture showing centralised entitlement resolution
     Placement: inline
     Suggested: Technical diagram with clear data flow -->

## Handling Edge Cases Gracefully

Real-world entitlements go beyond straightforward plan checks. Trials, add-ons, and custom arrangements all add complexity, but the entitlements pattern accommodates them cleanly.

Trials work by granting entitlements temporarily. A user on a free plan trial gets Pro entitlements for fourteen days. Your entitlement resolver combines the plan's standard entitlements with any temporary grants. Whether the user is on trial or a full subscription, your feature code sees the same entitlements.

Add-ons grant additional entitlements without changing the base plan. A Starter customer who purchases the "Advanced Analytics" add-on gets those entitlements layered on top of their standard Starter entitlements. The mapping becomes slightly more complex, but the feature checks remain unchanged.

Custom arrangements are simply plans with custom entitlement mappings. An enterprise customer needs SSO but wants to stay on the Pro price? Create a custom plan that grants Pro entitlements plus SSO. Your sales team can close the deal without waiting for engineering.

Downgrades require special consideration. When a user moves from Pro to Starter, they lose entitlements. What happens to data or artifacts associated with those lost capabilities? If a user had ten projects and Starter only allows five, you need a policy. Do you lock access to the extras? Archive them? Provide a grace period? The entitlements pattern doesn't answer these questions, but it makes them visible and explicit.

## The Feature Flag Connection

If you're already using feature flags for gradual rollouts and A/B testing, entitlements might feel redundant. Both control what users can access. But they serve different purposes and work best together.

Feature flags control rollout of functionality across your user base. They answer questions like "has this feature been released?" and "is this user in the experiment cohort?" Feature flags are typically boolean and managed by engineering.

Entitlements control access to functionality based on commercial relationships. They answer "has this user paid for this feature?" and "does this plan include this capability?" Entitlements are managed by product and business teams.

The two systems intersect at a clear boundary. A feature must pass both checks to be accessible: the feature flag must be enabled (the feature has shipped), and the entitlement must be present (the user has paid). During development, you might enable a feature flag for internal testing while no plans grant the entitlement yet. At release, you enable the feature flag broadly and add the entitlement to appropriate plans.

```javascript
async function canAccessFeature(user, featureKey, entitlementKey) {
    const flagEnabled = featureFlags.isEnabled(featureKey, user);
    const hasAccess = user.entitlements.includes(entitlementKey);
    return flagEnabled && hasAccess;
}
```

This separation keeps responsibilities clear. Engineers manage feature flags for technical rollout; product and business teams manage entitlements for commercial access.

## Migrating from Tier Checks

If your codebase already has tier checks scattered throughout, migrating to entitlements requires methodical effort. The good news is that you can migrate incrementally, wrapping existing checks without requiring a big-bang rewrite.

Start by cataloguing existing tier checks. Search your codebase for plan comparisons, tier references, and premium feature gates. This inventory shows you the scope of the migration and reveals patterns you can address systematically.

Create entitlements that match your current tier structure. If Pro includes features A, B, and C, create entitlements for each and grant them all to Pro. This maintains current behaviour while introducing the entitlement abstraction.

Replace tier checks one at a time. Each change should be behaviour-preserving; users should see exactly the same access before and after. This lets you verify the migration incrementally rather than hoping a large change is correct.

Once you've replaced all tier checks with entitlement checks, you have freedom to restructure. Tier names no longer appear in your codebase; only entitlement names remain. You can rename plans, split tiers, create custom bundles, and run promotions without touching feature code.

## Building for the Future

The entitlements pattern isn't just about surviving pricing changes. It's about building a foundation that supports the complexity your billing will eventually require.

Early-stage products have simple pricing: one or two tiers, clear feature boundaries, few exceptions. Tier checks work fine at this stage. But success creates complexity. More plans, more features, more exceptions, more customisation requests from sales. Products that built tier checks into their foundation pay that debt forever. Products that built entitlements adapt without rewrites.

The investment in entitlements pays off over time. Each pricing change that doesn't require engineering involvement is time saved. Each custom deal that's just configuration rather than code is velocity gained. Each feature addition that only touches one file is complexity avoided.

Your first pricing structure won't be your last. Build the abstraction that makes change cheap.

---

_Salable's [entitlements system](https://beta.salable.app/docs/understanding-entitlements) provides the mapping and resolution layer out of the box, so you can adopt the entitlements pattern without building the infrastructure yourself. Define capabilities in the dashboard and check them in your code with a single API call._
