# Slide Mobile Manager

Control your presentation slides from your phone, over the internet, while your computer stays on any network.

At a high level:

- You run a small **Agent** app on your computer (Windows).
- The Agent opens a secure WebSocket connection to a **Backend** running on Render.
- On your phone, you open a **Controller Web UI** (hosted on Netlify), type a short code, and tap **Next/Prev**.
- Those button presses travel through the backend to your Agent, which simulates right/left key presses with `pyautogui`.

![Architecture overview](docs/architecture.png)

The diagram shows:

- Presenter PC running the Agent, sending key presses to the slides.
- FastAPI backend (Render) in the middle, managing sessions and routing WebSocket messages.
- Controller Web UI on a phone (Netlify), where the user enters a short code and taps Next/Prev.

## Components Overview

- **Backend (FastAPI + WebSockets)**
	- File: `backend/app.py`
	- Hosted on Render at `https://slide-mobile-manager.onrender.com`.
	- Exposes WebSocket endpoints for:
		- `/ws/agent` – desktop agents register and receive commands.
		- `/ws/controller` – phone/web controllers join a session and send commands.
	- Maintains in-memory mappings of:
		- `agent_id \u2192 WebSocket`
		- `session_id \u2192 agent_id`
		- `session_id \u2192 [controller WebSockets]`
	- Periodically cleans up **idle sessions**:
		- Agents send periodic `agent_heartbeat` messages.
		- The backend tracks the last-seen time per `agent_id`.
		- Agents (and their sessions/controllers) that are inactive for a configured TTL are automatically removed.

- **Agent (Desktop Python app)**
	- File: `agent/main.py`
	- Runs on your presentation computer.
	- Connects to the backend via WebSocket.
	- Receives a unique `session_id` code (e.g. `8ABB57`) and prints it.
	- Listens for `command` messages and calls `pyautogui.press("right"/"left")`.

- **Controller Web UI (Static site)**
	- File: `controller/index.html`
	- Hosted on Netlify as a static site.
	- Mobile-friendly page with a join screen and big **Prev/Next** buttons.
	- Uses `navigator.wakeLock.request('screen')` on supported browsers to keep the phone screen awake.
	- Opens a WebSocket to the backend and sends `join_session` + `command` JSON messages.

The diagram would look like this (ASCII fallback if you don't add an image):

```text
Phone (Controller UI) --[wss]--> FastAPI Backend --[wss]--> Agent on PC --[keys]--> Slides
```

## 1. Local Development Setup

### Prerequisites

- Python 3.10+
- pip (Python package manager)
- On Windows, a virtual environment (recommended)

Create and activate a venv (once per machine):

```powershell
python -m venv .venv
& .venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

### Run backend locally

From the project root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --reload
```

Check health:

- `GET http://127.0.0.1:8000/health` \u2192 `{"status": "ok", "version": "0.1.0"}`

### Run the Agent locally (against local backend)

In a new terminal (with venv activated):

```powershell
$env:SLIDE_BACKEND_URL = "ws://127.0.0.1:8000/ws/agent"
.\.venv\Scripts\python.exe .\agent\main.py
```

You should see something like:

```text
[agent] Connecting to backend at ws://127.0.0.1:8000/ws/agent as agent_id=pc-XXXX....
========================================
Agent registered.
Your code: 8ABB57
Enter this code on the controller UI.
========================================
[agent] Waiting for commands (next/prev)...
```

### Open the Controller locally (for quick testing)

From the project root, serve static files:

```powershell
python -m http.server 8080
```

Open in a browser on the same machine:

- `http://127.0.0.1:8080/controller/`

Flow:

1. Make sure the backend and agent are running.
2. Note the `Your code: XXXXX` from the agent.
3. In the browser, enter that code and click **Join**.
4. Click **Next/Prev** and verify:
	 - Agent console logs the received commands.
	 - Your slide app (PowerPoint/Keynote) moves forward/back when it has focus.

> Wake Lock may not work over plain HTTP or on some desktop browsers; that's expected. It is designed for HTTPS + mobile.

## 2. Production Setup (Render + Netlify)

In production, the pieces are:

- **Backend** on Render: `https://slide-mobile-manager.onrender.com`
- **Controller UI** on Netlify: e.g. `https://YOUR-NETLIFY-SITE.netlify.app/`
- **Agent** running on the presenters PC

### 2.1 Backend on Render

Render configuration (already working in this project):

- Service type: **Web Service**
- Build command:
	- `pip install -r requirements.txt`
- Start command:
	- `uvicorn backend.app:app --host 0.0.0.0 --port $PORT`

After deployment, confirm:

- `https://slide-mobile-manager.onrender.com/health` returns the JSON health payload.

### 2.2 Controller on Netlify

Publish the `controller` folder as the site root.

- Build command: *(empty  no build)*
- Publish directory: `controller`

The important line in `controller/index.html` is:

```js
const BACKEND_WS_URL = (location.hostname === "localhost" || location.hostname === "127.0.0.1")
	? "ws://127.0.0.1:8000/ws/controller"
	: "wss://slide-mobile-manager.onrender.com/ws/controller";
```

So when the site runs on Netlify (`https://YOUR-NETLIFY-SITE.netlify.app`), the controller will open a WebSocket to the Render backend.

### 2.3 Agent pointing to Render

On the presenters Windows PC, with venv activated:

```powershell
$env:SLIDE_BACKEND_URL = "wss://slide-mobile-manager.onrender.com/ws/agent"
.\.venv\Scripts\python.exe .\agent\main.py
```

The agent will register with the Render backend and print a session code, exactly as in local dev.

### 2.4 End-to-end Usage (Presenter)

1. **Start the Agent** on your computer.
	 - A console window appears and prints: `Your code: 8ABB57`.
2. **Open the Controller** on your phone.
	 - Go to your Netlify URL, e.g. `https://YOUR-NETLIFY-SITE.netlify.app/`.
3. **Join the session.**
	 - Type the code from the agent (e.g. `8ABB57`) and tap **Join**.
4. **Control the slides.**
	 - With your slides app in full-screen and focused:
		 - **Next** button on the phone sends `command: "next"` \u2192 agent presses right arrow.
		 - **Prev** button sends `command: "prev"` \u2192 agent presses left arrow.
5. **Wake Lock.**
	 - On Android Chrome over HTTPS, the controller will try to keep the screen awake while the tab is visible.
	 - On browsers that dont support `navigator.wakeLock`, a friendly warning is shown.

## 3. Message Protocol

All messages are JSON objects sent over WebSocket with a `type` field.

### Types

- `agent_register`
- `agent_heartbeat`
- `session_assigned`
- `join_session`
- `command`

### Agent \u2192 Backend

**Register agent** (first message on `/ws/agent`):

```json
{
	"type": "agent_register",
	"agent_id": "pc-123456",
	"version": "1.0.0"
}
```

**Heartbeat** (periodic, optional):

```json
{
	"type": "agent_heartbeat",
	"agent_id": "pc-123456"
}
```

The backend uses these heartbeats to track activity and expire **idle agents and sessions** after a configurable timeout.

**Agent authentication (optional, shared secret)**

When enabled, each agent must include a shared secret in its `agent_register` message.

Backend configuration:

- Environment variable: `AGENT_SHARED_SECRET`
  - If unset/empty: auth is disabled (useful for local development).
  - If set: all agents must send a matching `secret` field.

Agent configuration:

- Environment variable: `AGENT_SHARED_SECRET` (same value as backend).
- The agent automatically includes this value in the `secret` field when registering.

Example agent_register with secret:

```json
{
	"type": "agent_register",
	"agent_id": "pc-123456",
	"version": "1.0.0",
	"secret": "<YOUR-SHARED-SECRET>"
}
```

If the secret is missing or incorrect while auth is enabled, the backend replies with:

```json
{
	"type": "error",
	"error": "unauthorized"
}
```

and closes the WebSocket. The Agent GUI will show a reconnecting/error status and keep retrying.

### Backend \u2192 Agent

**Session assigned** (response to `agent_register`):

```json
{
	"type": "session_assigned",
	"session_id": "ABCD12"
}
```

**Command** (forwarded from a controller):

```json
{
	"type": "command",
	"session_id": "ABCD12",
	"command": "next",
	"controller_id": "phone-xyz"
}
```

### Controller \u2192 Backend

**Join a session** (first message on `/ws/controller`):

```json
{
	"type": "join_session",
	"session_id": "ABCD12",
	"controller_id": "phone-xyz"
}
```

**Send a command**:

```json
{
	"type": "command",
	"session_id": "ABCD12",
	"command": "next",  
	"controller_id": "phone-xyz"
}
```

Currently accepted `command` values are:

- `"next"` \u2013 maps to right arrow key
- `"prev"` \u2013 maps to left arrow key

Any other `command` is ignored by the agent (logged but not executed).

## 4. Manual WebSocket Testing (Advanced)

If you want to test the backend without the Agent and Controller code, you can use a WebSocket client like Insomnia or wscat.

### Test `/ws/agent`

1. Connect to `ws://127.0.0.1:8000/ws/agent` (or `wss://slide-mobile-manager.onrender.com/ws/agent` in production).
2. Send:

```json
{
	"type": "agent_register",
	"agent_id": "pc-123",
	"version": "1.0.0"
}
```

3. You should receive:

```json
{
	"type": "session_assigned",
	"session_id": "<CODE>"
}
```

### Test `/ws/controller`

1. Connect to `ws://127.0.0.1:8000/ws/controller`.
2. First message:

```json
{
	"type": "join_session",
	"session_id": "<CODE>",
	"controller_id": "phone-1"
}
```

3. Then send a command:

```json
{
	"type": "command",
	"session_id": "<CODE>",
	"command": "next",
	"controller_id": "phone-1"
}
```

When a real agent is connected with that `session_id`, it will receive the same `command` payload.

## 5. Building the Windows Agent (.exe)

You can package the Agent into a single Windows executable so end users do not need Python or a virtual environment.

### 5.1 Install PyInstaller

From the project root, with your virtual environment activated:

```powershell
pip install pyinstaller
```

### 5.2 Build the executable

Run:

```powershell
pyinstaller --noconsole --onefile --name SlideMobileAgent agent\main.py
```

This creates:

- `dist/SlideMobileAgent.exe` – a single file you can distribute.

`--noconsole` ensures only the GUI window is shown when users run the agent.

### 5.3 Running the packaged Agent

On a presenter machine (no Python required):

1. Download / copy `SlideMobileAgent.exe`.
2. (Optional) Create a shortcut on the desktop.
3. Double-click the exe to launch.

If you want to point it to a different backend (for example, a staging or local server), you can set `SLIDE_BACKEND_URL` before starting it from a terminal:

```powershell
$env:SLIDE_BACKEND_URL = "wss://slide-mobile-manager.onrender.com/ws/agent"
dist\SlideMobileAgent.exe
```

If `SLIDE_BACKEND_URL` is not set, the agent uses the default backend URL compiled into `agent/main.py`.

## 6. Future Improvements

Planned enhancements:

- Packaged Windows installer/exe for the Agent (PyInstaller).
- Simple GUI for the Agent showing status + session code.
- Session timeouts and cleanup. **(Basic TTL-based cleanup is already implemented; this item covers making it configurable and more observable.)**
- Optional authentication / per-user tokens for agents.
- Analytics or basic metrics (e.g. number of sessions, commands per session).

Contributions and suggestions are welcome.
