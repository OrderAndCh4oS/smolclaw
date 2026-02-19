---
description: Connect AI assistants like Claude Code directly to the Salable API using the Model Context Protocol. Manage products, subscriptions, entitlements, and billing through natural language.
---

# Model Context Protocol (MCP)

## Overview

Salable exposes a **Model Context Protocol** server that lets AI assistants interact with your Salable organisation directly. Instead of writing API calls by hand, you can ask an AI assistant to create products, check subscriptions, manage entitlements, and more — all through natural conversation.

MCP is an open standard that connects AI tools to external services. Salable's MCP server provides tools spanning the entire API surface: products, plans, pricing, subscriptions, entitlements, carts, webhooks, usage metering, and everything else you can do through the REST API.

## Prerequisites

You need a Salable API key to authenticate MCP requests. You can create one in the Salable dashboard under **API Keys**, or use the REST API directly. The MCP server uses the same authentication as the rest of the API — your existing API key works.

Add your API key to your shell profile (`~/.zshrc`, `~/.bashrc`, or equivalent) so it's available whenever you open a terminal:

```bash
export SALABLE_API_KEY="your_api_key_here"
```

After adding the line, restart your terminal or run `source ~/.zshrc` (or `source ~/.bashrc`) to load it.

> **Important** MCP clients read environment variables from your shell, not from `.env` files. The `SALABLE_API_KEY` variable must be set in your shell environment before you launch your client, otherwise the MCP connection will fail. Never commit your API key to version control.

## Quick Setup

The fastest way to get started is to download the configuration file directly into your project:

```bash
curl -o .mcp.json https://beta.salable.app/mcp.json
```

This creates a `.mcp.json` file in your project root that AI assistants like Claude Code will detect automatically. The configuration references `${SALABLE_API_KEY}`, which Claude Code expands from your shell environment at startup.

Once you've set the environment variable in your shell profile (see Prerequisites above), open Claude Code in your project directory and it will connect to the Salable API automatically.

## Manual Setup

If you prefer to configure things manually or need to customise the setup, there are a couple of approaches.

### Project Configuration File

Create a `.mcp.json` file in your project root:

```json
{
    "mcpServers": {
        "salable": {
            "type": "http",
            "url": "https://beta.salable.app/api/mcp",
            "headers": {
                "Authorization": "Bearer ${SALABLE_API_KEY}"
            }
        }
    }
}
```

The `${SALABLE_API_KEY}` syntax tells the MCP client to expand the environment variable at runtime. This keeps your actual key out of the configuration file.

### Claude Code CLI

You can also add the server using the Claude Code CLI:

```bash
claude mcp add --transport http salable https://beta.salable.app/api/mcp \
  --header 'Authorization: Bearer ${SALABLE_API_KEY}'
```

This stores the configuration in your project's `.mcp.json` file automatically.

### Codex CLI

You can add the same server for Codex with:

```bash
codex mcp add salable \
  --url https://beta.salable.app/api/mcp \
  --bearer-token-env-var SALABLE_API_KEY
```

This stores the server in Codex's user config (`~/.codex/config.toml`).

### Scope Options

MCP servers can be configured at three levels:

**Project scope** (default) stores the configuration in `.mcp.json` at the project root. Everyone working on the project shares the same server configuration, though each person uses their own API key via the environment variable.

**User scope** stores the configuration in your home directory (`~/.claude/settings.json`). The server is available across all your projects without needing a `.mcp.json` in each one.

To add at user scope via the CLI:

```bash
claude mcp add --transport http --scope user salable https://beta.salable.app/api/mcp \
  --header 'Authorization: Bearer ${SALABLE_API_KEY}'
```

## Authentication

The MCP server authenticates requests using your API key passed in the `Authorization` header as a Bearer token. This is the same authentication mechanism used by the REST API.

OAuth is currently **not implemented** on Salable's MCP server. For clients that support OAuth login commands (for example, `codex mcp login <server-name>`), do not use login for this server. Configure the bearer token/API key instead (for example, `codex mcp add salable --url https://beta.salable.app/api/mcp --bearer-token-env-var SALABLE_API_KEY` or `claude mcp add --transport http salable https://beta.salable.app/api/mcp --header 'Authorization: Bearer ${SALABLE_API_KEY}'`).

Each request is rate limited. If you exceed the rate limit, the server responds with a standard JSON-RPC error and a 429 status code. Rate limits are shared with the REST API — MCP requests count toward the same quota.

The server operates in the same mode (Test or Live) as your API key. If you authenticate with a test mode API key, all operations happen in test mode. Use a live mode API key for production operations.

## Protocol Guarantees

Salable's MCP server follows these protocol rules to stay consistent with the MCP specification and SDK expectations:

- **JSON-RPC transport**: Requests and responses use JSON-RPC 2.0 envelopes.
- **Initialization lifecycle**:
    - `initialize` must be called before `tools/list` and `tools/call`.
    - Requests made before initialization return a JSON-RPC error (`code: -32002`, "Server not initialized").
- **Protocol version negotiation**:
    - The server advertises protocol version `2025-06-18`.
    - If a client requests an unsupported `protocolVersion`, the server returns `code: -32602`.
- **Tool calling semantics**:
    - Unknown tool names return a JSON-RPC protocol error (`code: -32602`).
    - Runtime errors inside a tool return a successful JSON-RPC response with MCP tool result `isError: true`.
- **Batch request support**:
    - JSON-RPC batch arrays are not supported.
    - Batch payloads return JSON-RPC invalid request (`code: -32600`).
- **Origin protection (DNS rebinding mitigation)**:
    - For HTTP transport, incoming `Origin` is validated.
    - If `MCP_ALLOWED_ORIGINS` is set, only listed origins are allowed.
    - Otherwise, the origin host must match the incoming `Host` header.
    - Invalid origins return HTTP `403`.

These guarantees are enforced by automated tests under `__tests__/mcp/`.

## Available Tools

The MCP server provides tools organised into functional categories. Each tool maps directly to a REST API endpoint, so the behaviour and parameters are identical to what you'd find in the API reference.

### Products and Pricing

These tools manage the core pricing hierarchy: Products contain Plans, which contain Line Items and Prices.

| Tool                         | Description                                                        |
| ---------------------------- | ------------------------------------------------------------------ |
| `products_list`              | List products for the organisation                                 |
| `products_create`            | Create a new product                                               |
| `products_get`               | Get a product by ID                                                |
| `products_update`            | Update a product                                                   |
| `products_delete`            | Delete a product                                                   |
| `products_archive`           | Archive a product                                                  |
| `products_copy_to_live_mode` | Copy a test mode product to live mode                              |
| `plans_list`                 | List plans for the organisation                                    |
| `plans_create`               | Create a new plan                                                  |
| `plans_get`                  | Get a plan by ID                                                   |
| `plans_update`               | Update a plan                                                      |
| `plans_delete`               | Delete a plan                                                      |
| `plans_archive`              | Archive a plan and its line items/prices                           |
| `plans_save`                 | Create or update a plan with line items, entitlements, and pricing |
| `line_items_list`            | List line items for the organisation                               |
| `line_items_get`             | Get a line item by ID                                              |
| `line_items_update`          | Update a line item                                                 |
| `line_items_delete`          | Delete a line item                                                 |
| `line_items_archive`         | Archive a line item and its prices                                 |
| `prices_list`                | List prices for the organisation                                   |
| `prices_get`                 | Get a price by ID                                                  |
| `prices_delete`              | Delete a price                                                     |
| `prices_archive`             | Archive a price                                                    |

### Subscriptions and Billing

Tools for managing the subscription lifecycle, invoices, and billing portal access.

| Tool                                  | Description                                                    |
| ------------------------------------- | -------------------------------------------------------------- |
| `subscriptions_list`                  | List subscriptions for the organisation                        |
| `subscriptions_get`                   | Get a subscription by ID                                       |
| `subscriptions_delete`                | Delete a subscription (test mode only)                         |
| `subscriptions_cancel`                | Cancel a subscription                                          |
| `subscriptions_auto_renew`            | Enable or disable auto-renewal                                 |
| `subscriptions_invoices`              | Get invoices for a subscription                                |
| `subscriptions_update_items`          | Add, remove, or replace plans on a subscription                |
| `subscriptions_portal`                | Generate a Stripe billing portal session URL                   |
| `subscriptions_batch`                 | Batch operations on subscriptions                              |
| `subscription_plans_list`             | List subscription plans for the organisation                   |
| `subscription_plans_get`              | Get a subscription plan by ID                                  |
| `subscription_plans_update_seats`     | Update seat quantity for a per-seat subscription plan          |
| `subscription_plan_line_items_get`    | Get a subscription plan line item by ID                        |
| `subscription_plan_line_items_update` | Update quantity for a subscription plan line item              |
| `subscription_plan_line_items_sync`   | Sync a subscription plan line item to the latest price version |

### Carts and Checkout

Tools for building and managing shopping carts and generating checkout sessions.

| Tool                | Description                                |
| ------------------- | ------------------------------------------ |
| `carts_list`        | List carts for the organisation            |
| `carts_create`      | Create a new cart                          |
| `carts_get`         | Get a cart by ID                           |
| `carts_update`      | Update a cart                              |
| `carts_abandon`     | Mark a cart as abandoned                   |
| `carts_checkout`    | Generate a Stripe checkout link for a cart |
| `carts_batch`       | Batch operations on carts                  |
| `cart_items_create` | Add an item to a cart                      |
| `cart_items_delete` | Remove an item from a cart                 |

### Entitlements and Access Control

Tools for managing feature access, grantees, groups, owners, and memberships.

| Tool                     | Description                              |
| ------------------------ | ---------------------------------------- |
| `entitlements_list`      | List entitlements for the organisation   |
| `entitlements_create`    | Create a new entitlement                 |
| `entitlements_get`       | Get an entitlement by ID                 |
| `entitlements_update`    | Update an entitlement                    |
| `entitlements_delete`    | Delete an entitlement                    |
| `entitlements_check`     | Check entitlements for a grantee         |
| `grantees_list`          | List grantees for the organisation       |
| `grantees_create`        | Create a new grantee                     |
| `grantees_get`           | Get a grantee by ID                      |
| `grantees_update`        | Update a grantee                         |
| `grantees_delete`        | Delete a grantee                         |
| `groups_list`            | List grantee groups for the organisation |
| `groups_create`          | Create a new grantee group               |
| `groups_get`             | Get a group by ID                        |
| `groups_update`          | Update a group                           |
| `groups_delete`          | Delete a group                           |
| `groups_manage_grantees` | Add or remove grantees from a group      |
| `owners_list`            | List owners for the organisation         |
| `owners_get`             | Get an owner by ID                       |
| `owners_update`          | Update an owner                          |
| `memberships_list`       | List memberships for the organisation    |
| `memberships_get`        | Get a membership by ID                   |

### Webhooks and Events

Tools for configuring webhook destinations and inspecting event delivery.

| Tool                  | Description                                       |
| --------------------- | ------------------------------------------------- |
| `webhooks_list`       | List webhooks for the organisation                |
| `webhooks_create`     | Create a new webhook                              |
| `webhooks_get`        | Get a webhook by ID                               |
| `webhooks_update`     | Update a webhook                                  |
| `webhooks_delete`     | Delete a webhook                                  |
| `events_list`         | List events for the organisation                  |
| `events_get`          | Get an event by ID                                |
| `event_attempts_list` | List event delivery attempts for the organisation |
| `destinations_list`   | List webhook destinations for the organisation    |
| `destinations_get`    | Get a destination by ID                           |
| `destinations_resend` | Resend an event to a destination                  |

### Usage and Metering

Tools for recording usage and managing meters for usage-based billing.

| Tool                  | Description                             |
| --------------------- | --------------------------------------- |
| `meters_list`         | List meters for the organisation        |
| `usage_records_list`  | List usage records for the organisation |
| `usage_record_create` | Record usage for metered billing        |
| `receipts_list`       | List receipts for the organisation      |
| `receipts_get`        | Get a receipt by ID                     |

### Administration

Tools for managing payment integrations, currency options, and pricing tiers.

| Tool                          | Description                                             |
| ----------------------------- | ------------------------------------------------------- |
| `payment_integrations_list`   | List payment integrations for the organisation          |
| `payment_integrations_create` | Create a new payment integration                        |
| `stripe_account_session`      | Create a Stripe account session for embedded components |
| `stripe_country_specs`        | Get supported currencies for a country                  |
| `currency_options_list`       | List currency options for the organisation              |
| `currency_options_get`        | Get a currency option by ID with pricing tiers          |
| `tiers_list`                  | List pricing tiers for the organisation                 |
| `tiers_get`                   | Get a pricing tier by ID                                |
| `tier_tags_list`              | List tier tags for the organisation                     |
| `tier_tags_create`            | Create a new tier tag                                   |

## Usage Examples

Once connected, you can interact with the Salable API conversationally. Here are some examples of what you might ask your AI assistant:

**Exploring your setup:** "List all my products and their plans" or "Show me the entitlements on the Pro plan."

**Managing subscriptions:** "How many active subscriptions do I have?" or "Cancel subscription sub_abc123."

**Configuring pricing:** "Create a new product called 'Starter' with a monthly plan at $29" or "Archive the old pricing tier."

**Checking access:** "Check what entitlements grantee user_456 has" or "List all members of the Enterprise group."

**Debugging:** "Show me the recent webhook events" or "List failed event delivery attempts" or "Resend the last failed webhook."

The AI assistant translates your requests into the appropriate tool calls, handles pagination, and presents results in a readable format. You get the full power of the Salable API without needing to remember endpoint URLs or request formats.

## Pagination

List tools return paginated results. Each response includes `nextCursor`, `previousCursor`, and `hasMore` fields. When `hasMore` is `true`, pass the `nextCursor` value as the `after` parameter in your next call to fetch the next page. To page backwards, pass `previousCursor` as the `before` parameter.

Most AI assistants handle pagination automatically when you ask for "all" of something — they'll keep calling the tool with cursors until `hasMore` is `false`. If you're building a custom MCP client, implement this loop yourself by checking `hasMore` after each response and passing the appropriate cursor.

Each page returns up to 25 items by default. You don't need to specify a page size — the server handles this consistently across all list endpoints.

## Session Management

The MCP server uses sessions to track initialization state. When your client sends its first `initialize` request, the server creates a session and returns a session ID in the `Mcp-Session-Id` response header. Your client must include this header in all subsequent requests.

Sessions are stored in Redis with a default TTL of one hour. After the TTL expires, the session is automatically cleaned up and your client will need to re-initialize. If your client receives a 404 response with "MCP session not found", the session has expired — send a new `initialize` request to create a fresh session.

To explicitly end a session, send a `DELETE` request to `/api/mcp` with the `Mcp-Session-Id` header. This immediately removes the session from Redis.

If your client needs to re-initialize an existing session (for example, after a reconnection), it can send a new `initialize` request with the existing `Mcp-Session-Id` header. The server will update the session and return the session ID in the response header.

## Troubleshooting

### Connection Refused

If your AI assistant can't connect to the MCP server, verify that `SALABLE_API_KEY` is set in your shell environment. Run `echo $SALABLE_API_KEY` in your terminal to check — if it's empty, the variable isn't set. Add it to your shell profile (`~/.zshrc` or `~/.bashrc`), then restart your terminal and relaunch your AI assistant. Note that `.env` files are not read automatically — the variable must be exported in your shell.

### Authentication Errors

A 401 response means the API key is missing or invalid. Check that your API key is correct and hasn't been revoked. You can verify the key works by testing it with a direct API call:

```bash
curl -H "Authorization: Bearer $SALABLE_API_KEY" https://beta.salable.app/api/products
```

If your MCP client asks you to run an OAuth login flow (for example, `codex mcp login <server-name>`), skip that flow for Salable. Use API key/bearer token configuration only (for example, `codex mcp add salable --url https://beta.salable.app/api/mcp --bearer-token-env-var SALABLE_API_KEY` or `claude mcp add --transport http salable https://beta.salable.app/api/mcp --header 'Authorization: Bearer ${SALABLE_API_KEY}'`).

### Rate Limiting

A 429 response indicates you've exceeded the rate limit. MCP requests share the same rate limit as REST API calls — each tool invocation counts as one API request toward your quota. Wait briefly and retry, or reduce the frequency of requests.

Rate limits are applied per tool, so calling `products_list` and `subscriptions_list` in quick succession draws from the same overall quota but is tracked under separate keys. If you're scripting against the MCP server, add a small delay between calls to avoid hitting the limit.

### Test Mode vs Live Mode

If you're not seeing the data you expect, check which mode your API key is for. Test mode keys only access test mode data, and live mode keys only access live mode data. This is the same behaviour as the REST API.

## Next Steps

Now that you have the MCP server connected, explore these related guides:

- **[Quick Start](/docs/quick-start)** - Set up your first product and subscription
- **[Products & Pricing](/docs/products-and-pricing)** - Detailed pricing configuration
- **[Core Concepts](/docs/core-concepts)** - Understand Salable's data model
- **[Subscriptions & Billing](/docs/subscriptions-and-billing)** - Subscription lifecycle management
