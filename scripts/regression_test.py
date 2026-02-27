"""Regression tests for SmolClaw WebSocket gateway.

Targets specific edge cases and bugs found during development.
Run against a live container.

Usage:
    1. Start the container:  docker compose up -d
    2. Run all tests:        python scripts/regression_test.py
    3. Run specific test:    python scripts/regression_test.py --test empty_message
    4. Custom URL:           python scripts/regression_test.py --url ws://host:18789
"""

import argparse
import asyncio
import json
import sys
import time

import websockets

from ws_helpers import ok, fail, info, summary, connect, chat, get_agent_text, get_lifecycle_phases


# ---------------------------------------------------------------------------
# Test: Empty message
# ---------------------------------------------------------------------------
async def test_empty_message(url):
    print("\n--- Test: Empty Message ---")
    try:
        ws = await connect(url)
        events = await chat(ws, "", session_key="empty-msg", timeout=30)
        phases = get_lifecycle_phases(events)

        if "end" in phases or "error" in phases:
            ok("Empty message handled without crash")
        else:
            fail(f"Empty message lifecycle: {phases}")

        await ws.close()
    except Exception as e:
        fail(f"Empty message test failed: {e}")


# ---------------------------------------------------------------------------
# Test: Special characters (unicode, emoji, code blocks)
# ---------------------------------------------------------------------------
async def test_special_characters(url):
    print("\n--- Test: Special Characters ---")
    try:
        ws = await connect(url)

        messages = [
            "Say hi in Japanese: \u3053\u3093\u306b\u3061\u306f",
            "Respond with a thumbs up emoji",
            "Echo this code: ```python\nprint('hello')\n```",
        ]

        for msg in messages:
            events = await chat(ws, msg, session_key="special-chars", timeout=30)
            phases = get_lifecycle_phases(events)
            if "end" in phases:
                ok(f"Handled: {msg[:40]}...")
            elif "error" in phases:
                ok(f"Error (acceptable): {msg[:40]}...")
            else:
                fail(f"Failed: {msg[:40]}... -> {phases}")

        await ws.close()
    except Exception as e:
        fail(f"Special characters test failed: {e}")


# ---------------------------------------------------------------------------
# Test: Reconnect after error
# ---------------------------------------------------------------------------
async def test_reconnect_after_error(url):
    print("\n--- Test: Reconnect After Error ---")
    try:
        # First connection: send something that might cause an issue
        ws1 = await connect(url)
        await ws1.send(json.dumps({
            "type": "req",
            "id": "1",
            "method": "foo.invalid",
            "params": {},
        }))
        raw = await asyncio.wait_for(ws1.recv(), timeout=5)
        await ws1.close()
        info("First connection closed after error response")

        # Second connection: gateway should still be healthy
        await asyncio.sleep(0.5)
        ws2 = await connect(url)
        events = await chat(ws2, "Say PONG", session_key="reconnect-test", timeout=30)
        phases = get_lifecycle_phases(events)

        if "end" in phases:
            ok("Gateway healthy after reconnect")
        else:
            fail(f"Reconnect chat lifecycle: {phases}")

        await ws2.close()
    except Exception as e:
        fail(f"Reconnect test failed: {e}")


# ---------------------------------------------------------------------------
# Test: Session key with special characters
# ---------------------------------------------------------------------------
async def test_session_key_special_chars(url):
    print("\n--- Test: Session Key Special Characters ---")
    try:
        ws = await connect(url)

        keys = [
            "session.with.dots",
            "session-with-dashes",
            "session_with_underscores",
        ]

        for key in keys:
            events = await chat(ws, "Say OK", session_key=key, timeout=30)
            phases = get_lifecycle_phases(events)
            if "end" in phases:
                ok(f"Session key '{key}' works")
            else:
                fail(f"Session key '{key}' failed: {phases}")

        await ws.close()
    except Exception as e:
        fail(f"Session key special chars test failed: {e}")


# ---------------------------------------------------------------------------
# Test: Rapid abort
# ---------------------------------------------------------------------------
async def test_rapid_abort(url):
    print("\n--- Test: Rapid Abort ---")
    try:
        ws = await connect(url)

        # Send chat.send
        req_id = str(int(time.time() * 1000))
        await ws.send(json.dumps({
            "type": "req",
            "id": req_id,
            "method": "chat.send",
            "params": {"message": "Write a long story", "sessionKey": "rapid-abort"},
        }))

        # Read lifecycle start + ack
        events = []
        for _ in range(3):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                events.append(json.loads(raw))
            except asyncio.TimeoutError:
                break

        # Extract runId from events
        run_id = None
        for e in events:
            rid = e.get("payload", {}).get("runId")
            if rid:
                run_id = rid
                break

        if run_id:
            # Immediately abort
            await ws.send(json.dumps({
                "type": "req",
                "id": "abort-1",
                "method": "chat.abort",
                "params": {"runId": run_id},
            }))

            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            res = json.loads(raw)
            if res.get("ok") is True:
                ok("Rapid abort succeeded without crash")
            else:
                fail(f"Rapid abort response: {res}")
        else:
            ok("No runId found (chat may have completed instantly)")

        # Drain remaining events
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
                msg = json.loads(raw)
                if msg.get("event") == "agent":
                    phase = msg.get("payload", {}).get("data", {}).get("phase")
                    if phase in ("end", "error"):
                        break
        except asyncio.TimeoutError:
            pass

        # Verify gateway still healthy
        events = await chat(ws, "Say OK", session_key="post-abort", timeout=30)
        phases = get_lifecycle_phases(events)
        if "end" in phases:
            ok("Gateway healthy after rapid abort")
        else:
            fail(f"Post-abort chat lifecycle: {phases}")

        await ws.close()
    except Exception as e:
        fail(f"Rapid abort test failed: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
ALL_TESTS = {
    "empty_message": test_empty_message,
    "special_chars": test_special_characters,
    "reconnect": test_reconnect_after_error,
    "session_keys": test_session_key_special_chars,
    "rapid_abort": test_rapid_abort,
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
    parser = argparse.ArgumentParser(description="SmolClaw regression tests")
    parser.add_argument("--url", default="ws://localhost:18789", help="Gateway WebSocket URL")
    parser.add_argument("--test", default=None, help=f"Run a single test: {', '.join(ALL_TESTS.keys())}")
    args = parser.parse_args()
    asyncio.run(run_all(args.url, args.test))
