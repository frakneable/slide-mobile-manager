# Slide Mobile Manager (backend)

This repository is being rebuilt as a multi-tenant slide controller platform.

The architecture splits into:
- **Backend (FastAPI)**: WebSocket hub that connects desktop agents and mobile controllers.
- **Agent**: Small desktop app running on the presenter PC, listening for commands.
- **Controller Web App**: Mobile-friendly UI (hosted over HTTPS) sending commands.

This README currently documents **step 1**: the backend protocol and basic FastAPI scaffolding.

## Backend Requirements

- Python 3.10+
- pip (Python package manager)

Install backend dependencies:

```powershell
pip install -r requirements.txt
```

Run the FastAPI app (dev):

```powershell
uvicorn backend.app:app --reload
```

Health check:

- `GET /health` → `{ "status": "ok", "version": "0.1.0" }`

## Message Protocol (Draft)

Messages are JSON sent over WebSockets (agent/controller ↔ backend). All messages share a `type` field.

### Common

Base envelope:

```json
{
	"type": "agent_register" | "agent_heartbeat" | "session_assigned" | "join_session" | "command"
}
```

### Agent → Backend

**Register agent**

```json
{
	"type": "agent_register",
	"agent_id": "pc-123456",
	"version": "1.0.0"
}
```

**Heartbeat**

```json
{
	"type": "agent_heartbeat",
	"agent_id": "pc-123456"
}
```

### Backend → Agent

**Session assigned**

```json
{
	"type": "session_assigned",
	"session_id": "ABCD12"
}
```

### Controller → Backend

**Join a session**

```json
{
	"type": "join_session",
	"session_id": "ABCD12",
	"controller_id": "phone-xyz"
}
```

**Send a command**

```json
{
	"type": "command",
	"session_id": "ABCD12",
	"command": "next",  // or "prev"
	"controller_id": "phone-xyz"
}
```

> Validation of `command` values (only `next` / `prev`) will be implemented when we wire the WebSocket endpoints in the next step.

## Next Steps

1. Connect an **agent** client to `ws://localhost:8000/ws/agent`.
2. Connect a **controller** client to `ws://localhost:8000/ws/controller`.
3. Verify commands flow only to the correct agent based on `session_id`.

### Manual WebSocket Test Flow

1. Start the backend:

```powershell
uvicorn backend.app:app --reload
```

2. As agent (use a WebSocket tester or simple script), connect to `/ws/agent` and send:

```json
{
	"type": "agent_register",
	"agent_id": "pc-123",
	"version": "1.0.0"
}
```

You should receive:

```json
{
	"type": "session_assigned",
	"session_id": "<CODE>"
}
```

3. As controller, connect to `/ws/controller` and send:

```json
{
	"type": "join_session",
	"session_id": "<CODE>",
	"controller_id": "phone-1"
}
```

4. From the same controller connection, send a command:

```json
{
	"type": "command",
	"session_id": "<CODE>",
	"command": "next",
	"controller_id": "phone-1"
}
```

The agent connection should receive the same `command` message, scoped to that `session_id`.
