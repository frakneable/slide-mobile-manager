"""Console-only desktop agent that connects to the backend WebSocket.

Behavior
--------
- Connects to /ws/agent
- Prints the assigned session code
- On command messages: presses left/right via pyautogui
- Sends periodic heartbeats
"""

import asyncio
import json
import os
import uuid
from typing import Optional

import pyautogui
import websockets
import contextlib


BACKEND_URL = os.getenv("SLIDE_BACKEND_URL", "wss://slide-mobile-manager.onrender.com/ws/agent")
AGENT_VERSION = "0.1.0"
HEARTBEAT_INTERVAL_SECONDS = 15.0


async def send_heartbeats(ws: websockets.WebSocketClientProtocol, agent_id: str) -> None:
    """Background task to send periodic heartbeats to the backend."""

    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            msg = {
                "type": "agent_heartbeat",
                "agent_id": agent_id,
            }
            try:
                await ws.send(json.dumps(msg))
            except Exception:
                # Connection likely closed; exit heartbeat loop
                return
    except asyncio.CancelledError:
        return


def handle_command(command: Optional[str]) -> None:
    """Translate a command string into a local key press.

    Unknown commands are logged and ignored.
    """

    if not command:
        print("[agent] Received empty/None command; ignoring.")
        return

    if command == "next":
        print("[agent] Executing NEXT (right arrow)")
        pyautogui.press("right")
    elif command == "prev":
        print("[agent] Executing PREV (left arrow)")
        pyautogui.press("left")
    else:
        # T3.3: unknown commands should be ignored, not crash
        print(f"[agent] Unknown command '{command}', ignoring.")


async def run_agent() -> None:
    agent_id = os.getenv("SLIDE_AGENT_ID", f"pc-{uuid.uuid4().hex[:8]}")

    print(f"[agent] Connecting to backend at {BACKEND_URL} as agent_id={agent_id} ...")

    async with websockets.connect(BACKEND_URL) as ws:
        # 1) Register
        register_msg = {
            "type": "agent_register",
            "agent_id": agent_id,
            "version": AGENT_VERSION,
        }
        await ws.send(json.dumps(register_msg))

        # 2) Wait for session_assigned
        raw = await ws.recv()
        data = json.loads(raw)
        if data.get("type") != "session_assigned":
            raise RuntimeError(f"Unexpected first message from backend: {data}")

        session_id = data["session_id"]
        print("========================================")
        print("Agent registered.")
        print(f"Your code: {session_id}")
        print("Enter this code on the controller UI.")
        print("========================================")

        # 3) Start heartbeat task
        heartbeat_task = asyncio.create_task(send_heartbeats(ws, agent_id))

        try:
            # 4) Listen for commands
            print("[agent] Waiting for commands (next/prev)...")
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    print("[agent] Received invalid JSON; ignoring.")
                    continue

                msg_type = msg.get("type")
                if msg_type != "command":
                    # Ignore other message types for now
                    continue

                cmd = msg.get("command")
                print(f"[agent] Received command for session {msg.get('session_id')}: {cmd}")
                handle_command(cmd)
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task


def main() -> None:
    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        print("\n[agent] Stopped by user.")


if __name__ == "__main__":
    main()
