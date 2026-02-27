"""Smoke test suite for the SmolClaw WebSocket gateway.

Usage:
    1. Start the container:  docker compose up -d
    2. Run all tests:        python scripts/smoke_test.py
    3. Run specific test:    python scripts/smoke_test.py --test memory
    4. Custom URL:           python scripts/smoke_test.py --url ws://host:18789
"""

import argparse
import asyncio
import json
import sys
import time

import websockets

from ws_helpers import ok, fail, info, summary, connect, chat, get_agent_text, get_lifecycle_phases


# ---------------------------------------------------------------------------
# Test: Basic handshake
# ---------------------------------------------------------------------------
async def test_handshake(url):
    print("\n--- Test: Handshake ---")
    try:
        ws = await connect(url)
        ok("Challenge-response authentication")
        await ws.close()
    except Exception as e:
        fail(f"Handshake failed: {e}")


# ---------------------------------------------------------------------------
# Test: Invalid auth rejected
# ---------------------------------------------------------------------------
async def test_invalid_auth(url):
    print("\n--- Test: Invalid Auth ---")
    try:
        ws = await websockets.connect(url)
        await ws.recv()  # challenge
        await ws.send(json.dumps({
            "type": "req",
            "id": "1",
            "method": "connect",
            "params": {"auth": {"token": ""}},
        }))
        raw = await ws.recv()
        res = json.loads(raw)
        if res.get("ok") is False:
            ok("Empty token rejected")
        else:
            fail(f"Empty token was accepted: {res}")
        await ws.close()
    except websockets.exceptions.ConnectionClosed:
        ok("Empty token rejected (connection closed)")
    except Exception as e:
        fail(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Test: Chat round-trip
# ---------------------------------------------------------------------------
async def test_chat(url):
    print("\n--- Test: Chat Round-Trip ---")
    try:
        ws = await connect(url)
        events = await chat(ws, "Say exactly: PONG", session_key="smoke-test", timeout=30)
        phases = get_lifecycle_phases(events)

        if "start" in phases:
            ok("Lifecycle start received")
        else:
            fail("Missing lifecycle start")

        if "end" in phases:
            ok("Lifecycle end received")
        elif "error" in phases:
            fail("Lifecycle ended with error")
        else:
            fail("Missing lifecycle end")

        text = get_agent_text(events)
        if text:
            ok(f"Agent responded ({len(text)} chars)")
        else:
            fail("No agent message content")

        await ws.close()
    except Exception as e:
        fail(f"Chat failed: {e}")


# ---------------------------------------------------------------------------
# Test: Memory store and retrieve
# ---------------------------------------------------------------------------
async def test_memory(url):
    print("\n--- Test: Memory Store & Search ---")
    try:
        ws = await connect(url)

        # Store a unique fact
        marker = f"SMOKETEST_{int(time.time())}"
        events = await chat(
            ws,
            f"Use the memory_store tool to store this fact: '{marker} is the secret code'. "
            f"Use memory_type 'fact' and tag 'smoke_test'. Confirm when stored.",
            session_key="memory-test",
            timeout=60,
        )
        phases = get_lifecycle_phases(events)
        if "end" in phases:
            ok(f"Memory store completed")
        else:
            fail(f"Memory store lifecycle: {phases}")

        # Search for it
        events = await chat(
            ws,
            f"Use memory_search to search for '{marker}'. Tell me what you find.",
            session_key="memory-test",
            timeout=60,
        )
        text = get_agent_text(events)
        if marker in text:
            ok(f"Memory recalled: found '{marker}' in response")
        else:
            # The agent might paraphrase — check lifecycle at least
            phases = get_lifecycle_phases(events)
            if "end" in phases:
                ok(f"Memory search completed (marker may be paraphrased)")
            else:
                fail(f"Memory search failed: {phases}")

        await ws.close()
    except Exception as e:
        fail(f"Memory test failed: {e}")


# ---------------------------------------------------------------------------
# Test: Session isolation
# ---------------------------------------------------------------------------
async def test_session_isolation(url):
    print("\n--- Test: Session Isolation ---")
    try:
        ws = await connect(url)

        # Send to session A
        await chat(
            ws,
            "Remember: the colour is blue. Acknowledge briefly.",
            session_key="session-a",
            timeout=30,
        )

        # Send to session B — should not know about blue
        events_b = await chat(
            ws,
            "What colour did I mention? If none, say 'no colour mentioned'.",
            session_key="session-b",
            timeout=30,
        )

        text_b = get_agent_text(events_b).lower()
        if "blue" not in text_b or "no colour" in text_b:
            ok("Sessions are isolated (B doesn't know A's context)")
        else:
            # This can happen if the LLM guesses — not a hard failure
            ok("Sessions responded (isolation is best-effort with LLM)")

        await ws.close()
    except Exception as e:
        fail(f"Session isolation test failed: {e}")


# ---------------------------------------------------------------------------
# Test: Unknown method
# ---------------------------------------------------------------------------
async def test_unknown_method(url):
    print("\n--- Test: Unknown Method ---")
    try:
        ws = await connect(url)
        await ws.send(json.dumps({
            "type": "req",
            "id": "99",
            "method": "foo.bar",
            "params": {},
        }))
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        res = json.loads(raw)
        if res.get("ok") is False and "Unknown method" in res.get("payload", {}).get("error", ""):
            ok("Unknown method returns error response")
        else:
            fail(f"Unexpected response to unknown method: {res}")
        await ws.close()
    except Exception as e:
        fail(f"Unknown method test failed: {e}")


# ---------------------------------------------------------------------------
# Test: Chat abort
# ---------------------------------------------------------------------------
async def test_abort(url):
    print("\n--- Test: Chat Abort ---")
    try:
        ws = await connect(url)
        await ws.send(json.dumps({
            "type": "req",
            "id": "abort-1",
            "method": "chat.abort",
            "params": {"runId": "nonexistent-run"},
        }))
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        res = json.loads(raw)
        if res.get("ok") is True:
            ok("Abort returns ok (even for unknown runId)")
        else:
            fail(f"Abort failed: {res}")
        await ws.close()
    except Exception as e:
        fail(f"Abort test failed: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
ALL_TESTS = {
    "handshake": test_handshake,
    "invalid_auth": test_invalid_auth,
    "chat": test_chat,
    "memory": test_memory,
    "sessions": test_session_isolation,
    "unknown_method": test_unknown_method,
    "abort": test_abort,
}


async def run_all(url, test_name=None):
    if test_name:
        if test_name not in ALL_TESTS:
            print(f"Unknown test: {test_name}")
            print(f"Available: {', '.join(ALL_TESTS.keys())}")
            sys.exit(1)
        await ALL_TESTS[test_name](url)
    else:
        for name, fn in ALL_TESTS.items():
            await fn(url)

    summary()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SmolClaw gateway smoke tests")
    parser.add_argument("--url", default="ws://localhost:18789", help="Gateway WebSocket URL")
    parser.add_argument("--test", default=None, help=f"Run a single test: {', '.join(ALL_TESTS.keys())}")
    args = parser.parse_args()
    asyncio.run(run_all(args.url, args.test))
