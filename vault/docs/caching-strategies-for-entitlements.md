---
description: Speed up entitlement checks with caching. This guide covers strategies for Node.js and Next.js applications, balancing performance with data accuracy. When to cache, how to invalidate, and patterns that scale.
---

# Caching Strategies for Entitlements

## Overview

Implementing effective caching for entitlement checks is crucial for building performant applications. This guide covers caching strategies specifically for Node.js and Next.js applications, helping you balance performance with data accuracy.

**Key benefits of caching:**

- Reduced API calls and faster response times
- Lower latency for feature access checks
- Better user experience during high traffic
- Reduced load on Salable's API

**Trade-offs to consider:**

- Cached data may be stale during subscription changes
- Cache invalidation adds complexity
- Memory usage for cache storage
- Consistency across distributed systems

## When to Cache

### Good Candidates for Caching

- **Frequent entitlement checks**: Features checked on every page load or API request
- **Stable subscriptions**: Long-term subscriptions that rarely change
- **Read-heavy patterns**: More reads than subscription updates
- **Session-based access**: User sessions with consistent subscription status

### Poor Candidates for Caching

- **Critical security checks**: Financial transactions, admin access, sensitive operations
- **Real-time subscription changes**: Immediately after upgrade/downgrade flows
- **Background jobs**: Batch processes that can tolerate API latency
- **Infrequent checks**: Features checked rarely don't benefit from caching

## Recommended Cache Durations

Choose cache TTL (Time-To-Live) based on your application's needs:

| Use Case              | Recommended TTL | Rationale                                  |
| --------------------- | --------------- | ------------------------------------------ |
| Short-lived sessions  | 5–10 minutes    | Quick invalidation for logged-out users    |
| Long-lived sessions   | 15–30 minutes   | Balance between performance and freshness  |
| Background jobs       | No cache        | Always check fresh data                    |
| Critical features     | 2–5 minutes     | Shorter TTL for important access decisions |
| Non-critical features | 30–60 minutes   | Longer TTL for less sensitive features     |

**Consider your billing cycle:**

- Monthly billing: Longer cache TTLs are acceptable (15–30 minutes)
- Usage-based billing: Shorter TTLs to reflect consumption changes (5–10 minutes)
- Perpetual licence: cache for the lifetime of the app

## Backend/API Implementation Example

Here's a simple in-memory caching pattern for your backend to reduce API calls:

```javascript
// entitlementCache.js
class EntitlementCache {
    constructor(ttlMs = 5 * 60 * 1000) {
        // 5 minute default
        this.cache = new Map();
        this.ttl = ttlMs;
    }

    get(granteeId) {
        const cached = this.cache.get(granteeId);
        if (!cached) return null;

        const age = Date.now() - cached.timestamp;
        if (age > this.ttl) {
            this.cache.delete(granteeId);
            return null;
        }
        return cached.entitlements;
    }

    set(granteeId, entitlements) {
        this.cache.set(granteeId, {
            entitlements,
            timestamp: Date.now()
        });
    }

    invalidate(granteeId) {
        this.cache.delete(granteeId);
    }
}

export default new EntitlementCache();
```

**Usage in your API/backend:**

```javascript
import cache from './entitlementCache.js';

async function getEntitlements(granteeId) {
    const cached = cache.get(granteeId);
    if (cached) return cached;

    const response = await fetch(`https://api.salable.app/api/entitlements/check?granteeId=${granteeId}`, {
        headers: { Authorization: `Bearer ${process.env.SALABLE_SECRET_KEY}` }
    });

    const data = await response.json();
    cache.set(granteeId, data.entitlements);
    return data.entitlements;
}
```

**Cache Invalidation via Webhooks:**

```javascript
app.post('/webhooks/salable', async (req, res) => {
    const event = req.body;

    if (['subscription.created', 'subscription.updated', 'subscription.cancelled'].includes(event.type)) {
        const grantees = await getGranteesFromSubscription(event.data.id);
        grantees.forEach(id => cache.invalidate(id));
    }

    res.json({ received: true });
});
```

## Best Practices

- **Choose appropriate TTLs**: 5–15 minutes for most use cases; shorter (2–5 min) for critical features
- **Invalidate on subscription changes**: Use webhook events to clear stale cache entries
- **Handle errors gracefully**: Fail securely by denying access when API calls fail
- **Consider distributed caching**: Use Redis or Valkey for multi-instance deployments
- **Use shorter TTLs for critical features**: Financial operations, admin access, etc.

## Backend/API Caching Considerations

**For single-instance backends**: In-memory caching (as shown above) is sufficient

**For production/multi-instance backends**: Use Redis or Valkey (Redis-compatible) for distributed caching to ensure consistency across instances

## Frontend Caching

For frontend applications, check entitlements through your own backend API endpoints rather than calling Salable directly. Your backend should implement the caching strategy above, and your frontend can use standard HTTP caching or state management libraries (React Query, SWR, etc.) to cache responses from your backend.

**Important: Cache Invalidation Limitations**

Frontend caches are difficult to invalidate because:

- Frontends don't receive webhook events when subscriptions change
- There's no way to notify the client when entitlements are updated server-side
- Frontends must poll or refetch from your backend to get fresh state

**Recommendations for frontend caching:**

- Use shorter TTLs (2–5 minutes) to reduce staleness
- Refetch entitlements after user actions that might change subscriptions (_eg_, after redirecting back from checkout)
- Consider manual refresh options for users ("Refresh subscription status")
- Accept that some delay in reflecting subscription changes is unavoidable on the frontend

Remember: Caching is an optimization strategy to improve performance. Implement what fits your architecture and scale needs.
