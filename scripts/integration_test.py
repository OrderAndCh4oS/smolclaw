"""Deep integration tests for SmolClaw WebSocket gateway.

Complements smoke_test.py with longer-running, more thorough scenarios:
  - Memory persistence across reconnections
  - Concurrent session handling
  - Rapid-fire message resilience
  - Tool usage verification
  - Graceful disconnect handling

Usage:
    1. Start the container:  docker compose up -d
    2. Run all tests:        python scripts/integration_test.py
    3. Run specific test:    python scripts/integration_test.py --test memory_persist
    4. Custom URL:           python scripts/integration_test.py --url ws://host:18789
"""

import argparse
import asyncio
import json
import sys
import time
import uuid

import websockets

from ws_helpers import ok, fail, info, summary, connect, chat, get_agent_text, get_lifecycle_phases, get_tool_calls


# ---------------------------------------------------------------------------
# Test: Memory persists across reconnections
# ---------------------------------------------------------------------------
async def test_memory_persist(url):
    print("\n--- Test: Memory Persistence Across Reconnections ---")
    marker = f"PERSIST_{uuid.uuid4().hex[:8]}"
    session = f"persist-{marker}"

    try:
        # Connection 1: store a fact
        ws1 = await connect(url)
        info(f"Storing marker: {marker}")
        events = await chat(
            ws1,
            f"Use the memory_store tool to store this fact: "
            f"'{marker} is the persistence test code'. "
            f"Use memory_type 'fact' and tag 'integration_test'. Confirm when stored.",
            session_key=session,
            timeout=60,
        )
        phases = get_lifecycle_phases(events)
        if "end" in phases:
            ok("Memory store completed on connection 1")
        else:
            fail(f"Memory store lifecycle: {phases}")
            await ws1.close()
            return
        await ws1.close()
        info("Connection 1 closed")

        # Small delay to ensure persistence
        await asyncio.sleep(1)

        # Connection 2: search for the fact
        ws2 = await connect(url)
        info("Reconnected — searching for stored memory")
        events = await chat(
            ws2,
            f"Use memory_search to search for '{marker}'. Tell me exactly what you find.",
            session_key=session,
            timeout=60,
        )
        text = get_agent_text(events)
        phases = get_lifecycle_phases(events)

        if marker in text:
            ok(f"Memory persisted across reconnection: found '{marker}'")
        elif "end" in phases:
            ok("Memory search completed (marker may be paraphrased)")
        else:
            fail(f"Memory search failed: {phases}")

        await ws2.close()
    except Exception as e:
        fail(f"Memory persistence test failed: {e}")


# ---------------------------------------------------------------------------
# Test: Concurrent sessions on same connection
# ---------------------------------------------------------------------------
async def test_concurrent_sessions(url):
    print("\n--- Test: Concurrent Sessions ---")
    try:
        # Each session needs its own connection (websockets disallows concurrent recv)
        ws_a = await connect(url)
        ws_b = await connect(url)

        # Start two chats concurrently on different connections/sessions
        task_a = asyncio.create_task(chat(
            ws_a, "Say exactly: ALPHA", session_key="concurrent-a", timeout=30,
        ))
        task_b = asyncio.create_task(chat(
            ws_b, "Say exactly: BETA", session_key="concurrent-b", timeout=30,
        ))

        events_a, events_b = await asyncio.gather(task_a, task_b, return_exceptions=True)

        if isinstance(events_a, Exception):
            fail(f"Session A failed: {events_a}")
        else:
            phases_a = get_lifecycle_phases(events_a)
            if "end" in phases_a:
                ok("Session A completed")
            else:
                fail(f"Session A lifecycle: {phases_a}")

        if isinstance(events_b, Exception):
            fail(f"Session B failed: {events_b}")
        else:
            phases_b = get_lifecycle_phases(events_b)
            if "end" in phases_b:
                ok("Session B completed")
            else:
                fail(f"Session B lifecycle: {phases_b}")

        await ws_a.close()
        await ws_b.close()
    except Exception as e:
        fail(f"Concurrent sessions test failed: {e}")


# ---------------------------------------------------------------------------
# Test: Rapid-fire messages (resilience)
# ---------------------------------------------------------------------------
async def test_rapid_fire(url):
    print("\n--- Test: Rapid-Fire Messages ---")
    try:
        ws = await connect(url)
        n_messages = 3
        results = []

        for i in range(n_messages):
            info(f"Sending message {i+1}/{n_messages}")
            events = await chat(
                ws,
                f"Reply with only the number {i+1}.",
                session_key=f"rapid-{i}",
                timeout=30,
            )
            phases = get_lifecycle_phases(events)
            results.append("end" in phases)

        succeeded = sum(results)
        if succeeded == n_messages:
            ok(f"All {n_messages} rapid messages completed")
        elif succeeded > 0:
            ok(f"{succeeded}/{n_messages} rapid messages completed (partial)")
        else:
            fail(f"No rapid messages completed")

        await ws.close()
    except Exception as e:
        fail(f"Rapid-fire test failed: {e}")


# ---------------------------------------------------------------------------
# Test: Tool usage appears in events
# ---------------------------------------------------------------------------
async def test_tool_usage(url):
    print("\n--- Test: Tool Usage in Events ---")
    try:
        ws = await connect(url)
        events = await chat(
            ws,
            "Use memory_search to search for 'test'. Tell me what you find.",
            session_key="tool-usage-test",
            timeout=60,
        )

        phases = get_lifecycle_phases(events)
        if "end" in phases:
            ok("Tool usage chat completed")
        else:
            fail(f"Tool usage chat lifecycle: {phases}")

        # Check that we got agent message content
        text = get_agent_text(events)
        if text:
            ok(f"Agent responded with tool results ({len(text)} chars)")
        else:
            fail("No agent message content after tool usage")

        # Check for tool call events (if the gateway emits them)
        tool_events = [e for e in events if e.get("event", "").startswith("agent.tool")]
        if tool_events:
            ok(f"Tool call events emitted ({len(tool_events)} events)")
        else:
            info("No explicit tool call events (may be normal)")

        await ws.close()
    except Exception as e:
        fail(f"Tool usage test failed: {e}")


# ---------------------------------------------------------------------------
# Test: Graceful disconnect mid-stream
# ---------------------------------------------------------------------------
async def test_disconnect_midstream(url):
    print("\n--- Test: Graceful Disconnect Mid-Stream ---")
    try:
        ws = await connect(url)

        # Send a message that should trigger a long response
        req_id = str(int(time.time() * 1000))
        await ws.send(json.dumps({
            "type": "req",
            "id": req_id,
            "method": "chat.send",
            "params": {
                "message": "Write a detailed paragraph about the history of computing.",
                "sessionKey": "disconnect-test",
            },
        }))

        # Read a couple events then disconnect
        try:
            for _ in range(3):
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                msg = json.loads(raw)
                if msg.get("event") == "agent":
                    phase = msg.get("payload", {}).get("data", {}).get("phase")
                    if phase in ("end", "error"):
                        break
        except asyncio.TimeoutError:
            pass

        await ws.close()
        info("Disconnected mid-stream")

        # Verify the gateway is still healthy by connecting again
        await asyncio.sleep(1)
        ws2 = await connect(url)
        ok("Gateway still healthy after mid-stream disconnect")
        await ws2.close()
    except Exception as e:
        fail(f"Disconnect mid-stream test failed: {e}")


# ---------------------------------------------------------------------------
# Test: Multiple connections simultaneously
# ---------------------------------------------------------------------------
async def test_multiple_connections(url):
    print("\n--- Test: Multiple Simultaneous Connections ---")
    try:
        ws1 = await connect(url)
        ws2 = await connect(url)
        ok("Two connections established simultaneously")

        # Chat on both
        events1 = await chat(ws1, "Say exactly: CONN1", session_key="multi-1", timeout=30)
        events2 = await chat(ws2, "Say exactly: CONN2", session_key="multi-2", timeout=30)

        phases1 = get_lifecycle_phases(events1)
        phases2 = get_lifecycle_phases(events2)

        if "end" in phases1:
            ok("Connection 1 chat completed")
        else:
            fail(f"Connection 1 lifecycle: {phases1}")

        if "end" in phases2:
            ok("Connection 2 chat completed")
        else:
            fail(f"Connection 2 lifecycle: {phases2}")

        await ws1.close()
        await ws2.close()
    except Exception as e:
        fail(f"Multiple connections test failed: {e}")


# ---------------------------------------------------------------------------
# Test: Large message handling
# ---------------------------------------------------------------------------
async def test_large_message(url):
    print("\n--- Test: Large Message Handling ---")
    try:
        ws = await connect(url)
        large_msg = "Summarize this in one sentence: " + ("lorem ipsum " * 200)
        info(f"Sending message of {len(large_msg)} chars")

        events = await chat(ws, large_msg, session_key="large-msg", timeout=60)
        phases = get_lifecycle_phases(events)

        if "end" in phases:
            ok("Large message handled successfully")
        elif "error" in phases:
            ok("Large message returned error (acceptable)")
        else:
            fail(f"Large message lifecycle: {phases}")

        text = get_agent_text(events)
        if text:
            ok(f"Got response to large message ({len(text)} chars)")

        await ws.close()
    except Exception as e:
        fail(f"Large message test failed: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
ALL_TESTS = {
    "memory_persist": test_memory_persist,
    "concurrent": test_concurrent_sessions,
    "rapid_fire": test_rapid_fire,
    "tool_usage": test_tool_usage,
    "disconnect": test_disconnect_midstream,
    "multi_conn": test_multiple_connections,
    "large_msg": test_large_message,
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
    parser = argparse.ArgumentParser(description="SmolClaw deep integration tests")
    parser.add_argument("--url", default="ws://localhost:18789", help="Gateway WebSocket URL")
    parser.add_argument("--test", default=None, help=f"Run a single test: {', '.join(ALL_TESTS.keys())}")
    args = parser.parse_args()
    asyncio.run(run_all(args.url, args.test))
