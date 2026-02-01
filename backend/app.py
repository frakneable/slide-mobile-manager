from enum import Enum
from typing import Dict, List, Literal, Optional

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import asyncio
import json
import os
import secrets
import time


def _log(msg: str) -> None:
    """Simple stdout logger for debugging."""

    print(f"[backend] {msg}")


class MessageType(str, Enum):
    AGENT_REGISTER = "agent_register"
    AGENT_HEARTBEAT = "agent_heartbeat"
    SESSION_ASSIGNED = "session_assigned"
    JOIN_SESSION = "join_session"
    COMMAND = "command"


class BaseMessage(BaseModel):
    """Base envelope for all messages passed over WebSocket.

    The concrete shape depends on `type`.
    """

    type: MessageType


class AgentRegisterMessage(BaseMessage):
    type: Literal[MessageType.AGENT_REGISTER]
    agent_id: str
    version: str
    # Optional shared secret for simple agent authentication.
    secret: Optional[str] = None


class AgentHeartbeatMessage(BaseMessage):
    type: Literal[MessageType.AGENT_HEARTBEAT]
    agent_id: str


class SessionAssignedMessage(BaseMessage):
    type: Literal[MessageType.SESSION_ASSIGNED]
    session_id: str


class JoinSessionMessage(BaseMessage):
    type: Literal[MessageType.JOIN_SESSION]
    session_id: str
    controller_id: str


class CommandMessage(BaseMessage):
    type: Literal[MessageType.COMMAND]
    session_id: str
    command: str  # "next" | "prev" (validated later)
    controller_id: Optional[str] = None


SESSION_TTL_SECONDS = 10 * 60  # 10 minutes
CLEANUP_INTERVAL_SECONDS = 60  # 1 minute

# Optional shared secret used to authenticate agents on register.
AGENT_SHARED_SECRET = os.getenv("AGENT_SHARED_SECRET")


class SessionManager:
    """In-memory tracking of agents, sessions and controllers.

    - Each agent registers once and receives a session_id.
    - Controllers join by session_id.
    - Commands from controllers are forwarded to the owning agent.
    """

    def __init__(self) -> None:
        self.agents: Dict[str, WebSocket] = {}
        self.sessions: Dict[str, str] = {}  # session_id -> agent_id
        self.controllers: Dict[str, List[WebSocket]] = {}  # session_id -> [ws, ...]
        # Last time we saw a heartbeat or registration from each agent_id (epoch seconds)
        self.agent_last_seen: Dict[str, float] = {}

    @staticmethod
    def _new_session_id() -> str:
        # Short, human-friendly code (e.g. 6 hex chars)
        return secrets.token_hex(3).upper()

    async def register_agent(self, ws: WebSocket, msg: AgentRegisterMessage) -> str:
        agent_id = msg.agent_id
        self.agents[agent_id] = ws

        # Track last-seen from this agent for TTL-based cleanup
        self.agent_last_seen[agent_id] = time.time()

        # Create a new session for this agent
        session_id = self._new_session_id()
        self.sessions[session_id] = agent_id
        self.controllers.setdefault(session_id, [])

        _log(f"register_agent: agent_id={agent_id}, session_id={session_id}")

        assigned = SessionAssignedMessage(type=MessageType.SESSION_ASSIGNED, session_id=session_id)
        await ws.send_text(assigned.model_dump_json())
        return session_id

    def touch_agent(self, agent_id: str) -> None:
        """Update last-seen timestamp for an agent (on register/heartbeat)."""

        self.agent_last_seen[agent_id] = time.time()

    def remove_agent(self, ws: WebSocket) -> None:
        # Find agent_id by websocket instance
        to_remove: Optional[str] = None
        for agent_id, socket in self.agents.items():
            if socket is ws:
                to_remove = agent_id
                break

        if to_remove is None:
            _log("remove_agent: websocket not found in agents map")
            return

        _log(f"remove_agent: agent_id={to_remove}")
        del self.agents[to_remove]
        self.agent_last_seen.pop(to_remove, None)

        # Remove any sessions owned by this agent
        sessions_to_remove = [sid for sid, aid in self.sessions.items() if aid == to_remove]
        for sid in sessions_to_remove:
            _log(f"remove_agent: removing session_id={sid}")
            self.sessions.pop(sid, None)
            self.controllers.pop(sid, None)

    async def cleanup_expired_sessions(self) -> None:
        """Drop agents (and their sessions/controllers) that have been idle beyond TTL."""

        if not self.agent_last_seen:
            return

        now = time.time()
        cutoff = now - SESSION_TTL_SECONDS
        for agent_id, last_seen in list(self.agent_last_seen.items()):
            if last_seen < cutoff:
                ws = self.agents.get(agent_id)
                _log(
                    f"cleanup_expired_sessions: expiring agent_id={agent_id}, "
                    f"last_seen={last_seen}, cutoff={cutoff}"
                )
                if ws is not None:
                    # This will also remove sessions and controllers for this agent
                    self.remove_agent(ws)
                else:
                    # If websocket is already gone, just clean up bookkeeping
                    self.agent_last_seen.pop(agent_id, None)

    async def cleanup_loop(self) -> None:
        """Background task: periodically call cleanup_expired_sessions."""

        _log("cleanup_loop: started")
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            try:
                await self.cleanup_expired_sessions()
            except Exception as exc:  # defensive logging
                _log(f"cleanup_loop: error during cleanup: {exc}")

    async def add_controller(self, ws: WebSocket, msg: JoinSessionMessage) -> bool:
        session_id = msg.session_id
        if session_id not in self.sessions:
            _log(f"add_controller: session_id={session_id} not found")
            return False
        _log(f"add_controller: session_id={session_id}, controller_id={msg.controller_id}")
        self.controllers.setdefault(session_id, []).append(ws)
        return True

    def remove_controller(self, ws: WebSocket) -> None:
        for sid, sockets in list(self.controllers.items()):
            if ws in sockets:
                sockets.remove(ws)
                if not sockets:
                    _log(f"remove_controller: last controller removed for session_id={sid}")
                    self.controllers.pop(sid, None)

    async def forward_command(self, msg: CommandMessage) -> None:
        # Simple validation of command for now
        if msg.command not in {"next", "prev"}:
            _log(f"forward_command: invalid command='{msg.command}' for session_id={msg.session_id}")
            return

        agent_id = self.sessions.get(msg.session_id)
        if not agent_id:
            _log(f"forward_command: no agent for session_id={msg.session_id}")
            return
        ws = self.agents.get(agent_id)
        if not ws:
            _log(f"forward_command: agent websocket missing for agent_id={agent_id}")
            return
        _log(f"forward_command: session_id={msg.session_id}, command={msg.command}, agent_id={agent_id}")
        await ws.send_text(msg.model_dump_json())


manager = SessionManager()


def _is_agent_authorized(msg: AgentRegisterMessage) -> bool:
    """Return True if this agent is allowed to register.

    If AGENT_SHARED_SECRET is not set, auth is effectively disabled (for local dev).
    If it is set, the agent must provide a matching `secret`.
    """

    if not AGENT_SHARED_SECRET:
        return True
    # When auth is enabled, require an exact match.
    provided = getattr(msg, "secret", None)
    return provided == AGENT_SHARED_SECRET


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context: start background cleanup loop on startup."""

    asyncio.create_task(manager.cleanup_loop())
    yield


app = FastAPI(title="Slide Remote Backend", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """Simple health check for the backend service."""

    return {"status": "ok", "version": app.version}


@app.websocket("/ws/agent")
async def agent_ws(websocket: WebSocket) -> None:
    """WebSocket endpoint for desktop agents.

    First message must be `agent_register`; backend replies with `session_assigned`.
    """

    await websocket.accept()
    _log("/ws/agent: connection accepted")
    try:
        first_raw = await websocket.receive_text()
        _log(f"/ws/agent: first message raw={first_raw}")
        data = json.loads(first_raw)

        # Expect a plain string value like "agent_register" in JSON
        if data.get("type") != MessageType.AGENT_REGISTER.value:
            _log(f"/ws/agent: unexpected first type={data.get('type')}, closing")
            await websocket.close(code=4000)
            return

        msg = AgentRegisterMessage(**data)

        # Enforce optional shared-secret authentication for agents.
        if not _is_agent_authorized(msg):
            _log(f"/ws/agent: unauthorized agent_register from agent_id={msg.agent_id}")
            try:
                await websocket.send_text(json.dumps({"type": "error", "error": "unauthorized"}))
            except Exception:
                pass
            await websocket.close(code=4401)
            return

        await manager.register_agent(websocket, msg)

        # Keep the connection open for heartbeats / future extensions
        while True:
            raw = await websocket.receive_text()
            _log(f"/ws/agent: received raw={raw}")
            data = json.loads(raw)
            # Heartbeats come as {"type": "agent_heartbeat", ...}
            if data.get("type") == MessageType.AGENT_HEARTBEAT.value:
                # Validate payload and update last-seen for TTL purposes
                hb = AgentHeartbeatMessage(**data)
                manager.touch_agent(hb.agent_id)
                _log(f"/ws/agent: heartbeat from agent_id={hb.agent_id}")
            # Other message types from agents can be handled here later

    except WebSocketDisconnect:
        _log("/ws/agent: WebSocketDisconnect")
        manager.remove_agent(websocket)


@app.websocket("/ws/controller")
async def controller_ws(websocket: WebSocket) -> None:
    """WebSocket endpoint for phone/web controllers.

    First message must be `join_session`; subsequent messages can be `command`.
    """

    await websocket.accept()
    _log("/ws/controller: connection accepted")
    try:
        first_raw = await websocket.receive_text()
        _log(f"/ws/controller: first message raw={first_raw}")
        data = json.loads(first_raw)

        # First controller message must be {"type": "join_session", ...}
        if data.get("type") != MessageType.JOIN_SESSION.value:
            _log(f"/ws/controller: unexpected first type={data.get('type')}, closing")
            await websocket.close(code=4001)
            return

        join_msg = JoinSessionMessage(**data)
        ok = await manager.add_controller(websocket, join_msg)
        if not ok:
            await websocket.send_text(json.dumps({"type": "error", "error": "session_not_found"}))
            await websocket.close(code=4404)
            return

        # Receive controller commands
        while True:
            raw = await websocket.receive_text()
            _log(f"/ws/controller: received raw={raw}")
            data = json.loads(raw)
            # Controller commands are plain JSON with type "command"
            if data.get("type") != MessageType.COMMAND.value:
                _log(f"/ws/controller: ignoring non-command type={data.get('type')}")
                continue
            cmd_msg = CommandMessage(**data)
            await manager.forward_command(cmd_msg)

    except WebSocketDisconnect:
        _log("/ws/controller: WebSocketDisconnect")
        manager.remove_controller(websocket)
