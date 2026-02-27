"""Shared helpers for SmolClaw WebSocket test scripts (smoke, integration, regression)."""

import asyncio
import json
import sys
import time

import websockets

PASS = 0
FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  \033[32m[PASS]\033[0m {msg}")


def fail(msg):
    global FAIL
    FAIL += 1
    print(f"  \033[31m[FAIL]\033[0m {msg}")


def info(msg):
    print(f"  \033[36m[INFO]\033[0m {msg}")


def summary():
    print(f"\n{'='*40}")
    print(f"  \033[32m{PASS} passed\033[0m, \033[31m{FAIL} failed\033[0m")
    if FAIL > 0:
        sys.exit(1)


async def connect(url, token="test"):
    """Connect and authenticate, return the websocket."""
    ws = await websockets.connect(url)
    await ws.recv()  # challenge
    await ws.send(json.dumps({
        "type": "req",
        "id": "auth",
        "method": "connect",
        "params": {"auth": {"token": token}},
    }))
    raw = await ws.recv()
    hello = json.loads(raw)
    if not hello.get("ok"):
        raise ConnectionError(f"Auth failed: {hello}")
    return ws


async def chat(ws, message, session_key="default", timeout=60):
    """Send a chat message and collect all events until lifecycle end."""
    req_id = str(int(time.time() * 1000))
    await ws.send(json.dumps({
        "type": "req",
        "id": req_id,
        "method": "chat.send",
        "params": {"message": message, "sessionKey": session_key},
    }))

    events = []
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        events.append(msg)
        if msg.get("event") == "agent":
            phase = msg.get("payload", {}).get("data", {}).get("phase")
            if phase in ("end", "error"):
                break

    return events


def get_agent_text(events):
    """Extract concatenated agent message text from events."""
    parts = []
    for e in events:
        if e.get("event") == "agent.message":
            parts.append(e["payload"].get("content", ""))
    return " ".join(parts)


def get_lifecycle_phases(events):
    return [
        e["payload"]["data"]["phase"]
        for e in events
        if e.get("event") == "agent"
    ]


def get_tool_calls(events):
    """Extract tool call events from the stream."""
    return [
        e["payload"]
        for e in events
        if e.get("event") == "agent.tool_call"
    ]
