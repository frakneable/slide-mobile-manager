"""GUI-based desktop agent that connects to the backend WebSocket.

Behavior
--------
- Runs a small Tkinter window (no console needed for end users).
- Connects to /ws/agent (local or Render backend).
- Shows the current session code and connection status.
- On command messages: presses left/right via pyautogui.
- Sends periodic heartbeats and auto-reconnects on disconnect.
"""

import asyncio
import json
import os
import threading
import queue
import uuid
from dataclasses import dataclass, field
from typing import Optional

import pyautogui
import websockets
from websockets.exceptions import ConnectionClosedError

try:
    import tkinter as tk
    from tkinter import ttk
except Exception:  # pragma: no cover - Tkinter may not be available in some envs
    tk = None
    ttk = None


BACKEND_URL = os.getenv("SLIDE_BACKEND_URL", "wss://slide-mobile-manager.onrender.com/ws/agent")
AGENT_VERSION = "0.1.0"
HEARTBEAT_INTERVAL_SECONDS = 15.0
RECONNECT_DELAY_SECONDS = 5.0

pyautogui.FAILSAFE = False


@dataclass
class UiState:
    running: bool = True
    status_text: str = "Starting..."
    session_id: str = "-"
    last_error: Optional[str] = None


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
        print(f"[agent] Unknown command '{command}', ignoring.")


async def send_heartbeats(ws: websockets.WebSocketClientProtocol, agent_id: str, ui_state: UiState) -> None:
    """Background task to send periodic heartbeats to the backend."""

    try:
        while ui_state.running:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            msg = {"type": "agent_heartbeat", "agent_id": agent_id}
            try:
                await ws.send(json.dumps(msg))
            except Exception:
                return
    except asyncio.CancelledError:
        return


async def agent_loop(ui_state: UiState, ui_queue: "queue.Queue[dict]") -> None:
    """Main reconnecting loop for the agent WebSocket connection."""

    agent_id = os.getenv("SLIDE_AGENT_ID", f"pc-{uuid.uuid4().hex[:8]}")

    while ui_state.running:
        ui_state.status_text = "Connecting to backend..."
        ui_queue.put({"type": "status"})
        print(f"[agent] Connecting to backend at {BACKEND_URL} as agent_id={agent_id} ...")

        try:
            async with websockets.connect(BACKEND_URL) as ws:
                # Register
                register_msg = {
                    "type": "agent_register",
                    "agent_id": agent_id,
                    "version": AGENT_VERSION,
                }
                await ws.send(json.dumps(register_msg))

                # Wait for session_assigned
                raw = await ws.recv()
                data = json.loads(raw)
                if data.get("type") != "session_assigned":
                    raise RuntimeError(f"Unexpected first message from backend: {data}")

                ui_state.session_id = data["session_id"]
                ui_state.status_text = "Connected. Waiting for commands..."
                ui_state.last_error = None
                ui_queue.put({"type": "session"})
                print("========================================")
                print("Agent registered.")
                print(f"Your code: {ui_state.session_id}")
                print("Enter this code on the controller UI.")
                print("========================================")

                # Start heartbeat task
                heartbeat_task = asyncio.create_task(send_heartbeats(ws, agent_id, ui_state))

                try:
                    # Listen for commands
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            print("[agent] Received invalid JSON; ignoring.")
                            continue

                        if msg.get("type") != "command":
                            continue

                        cmd = msg.get("command")
                        print(f"[agent] Received command for session {msg.get('session_id')}: {cmd}")
                        handle_command(cmd)
                finally:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass

        except (ConnectionClosedError, OSError) as exc:
            ui_state.last_error = str(exc)
            if not ui_state.running:
                break
            ui_state.status_text = "Disconnected. Reconnecting..."
            ui_queue.put({"type": "status"})
            print(f"[agent] Connection closed, will retry in {RECONNECT_DELAY_SECONDS}s: {exc}")
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)
        except Exception as exc:  # unexpected errors
            ui_state.last_error = str(exc)
            if not ui_state.running:
                break
            ui_state.status_text = "Error. Reconnecting..."
            ui_queue.put({"type": "status"})
            print(f"[agent] Unexpected error, will retry in {RECONNECT_DELAY_SECONDS}s: {exc}")
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)


def start_agent_worker(ui_state: UiState, ui_queue: "queue.Queue[dict]") -> None:
    """Entry point for the background thread running the asyncio loop."""

    async def _runner() -> None:
        await agent_loop(ui_state, ui_queue)

    asyncio.run(_runner())


def run_gui() -> None:
    if tk is None:
        raise RuntimeError("Tkinter is not available in this environment.")

    ui_state = UiState()
    ui_queue: "queue.Queue[dict]" = queue.Queue()

    # Start background worker thread
    worker = threading.Thread(target=start_agent_worker, args=(ui_state, ui_queue), daemon=True)
    worker.start()

    root = tk.Tk()
    root.title("Slide Mobile Agent")
    root.resizable(False, False)

    main_frame = ttk.Frame(root, padding=16)
    main_frame.grid(row=0, column=0, sticky="nsew")

    tk.Label(main_frame, text="Slide Mobile Agent", font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 8))

    tk.Label(main_frame, text="Session code:", font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w")
    session_var = tk.StringVar(value="-")
    session_label = tk.Label(main_frame, textvariable=session_var, font=("Consolas", 14, "bold"))
    session_label.grid(row=1, column=1, sticky="e")

    tk.Label(main_frame, text="Status:", font=("Segoe UI", 10)).grid(row=2, column=0, sticky="w", pady=(8, 0))
    status_var = tk.StringVar(value=ui_state.status_text)
    status_label = tk.Label(main_frame, textvariable=status_var, font=("Segoe UI", 9), wraplength=260, justify="left")
    status_label.grid(row=2, column=1, sticky="w", pady=(8, 0))

    def on_quit() -> None:
        ui_state.running = False
        root.destroy()

    quit_btn = ttk.Button(main_frame, text="Quit", command=on_quit)
    quit_btn.grid(row=3, column=0, columnspan=2, pady=(16, 0))

    def poll_queue() -> None:
        while True:
            try:
                msg = ui_queue.get_nowait()
            except queue.Empty:
                break
            if msg.get("type") in {"status", "session"}:
                session_var.set(ui_state.session_id or "-")
                status_text = ui_state.status_text
                if ui_state.last_error:
                    status_text = f"{status_text}\nLast error: {ui_state.last_error}"
                status_var.set(status_text)
        if ui_state.running:
            root.after(500, poll_queue)

    root.after(500, poll_queue)
    root.mainloop()


def main() -> None:
    run_gui()


if __name__ == "__main__":
    main()
