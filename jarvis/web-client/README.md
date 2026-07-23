# ZEMARK — LiveKit Voice Web Client

A minimal, self-contained browser client that lets a user **talk to the ZEMARK
assistant by voice**. It publishes the microphone, subscribes to the agent's
audio, and shows connection state.

It talks to the Python LiveKit agent in
[`../zemark/livekit_agent.py`](../zemark/livekit_agent.py), which registers with
`agent_name="zemark"` via `@server.rtc_session(agent_name="zemark")`.

> **Untested at runtime.** This code was written against the documented LiveKit
> APIs but has not been executed in this environment. Verify locally before
> relying on it. Dependency versions are pinned to what was verified (July 2026).

## Pieces

| File | What it is |
| --- | --- |
| `server/token-server.js` | Tiny Express server that mints LiveKit access tokens. Keeps the API secret server-side. |
| `index.html` + `src/main.js` | Vite + vanilla-JS frontend: a "Falar com ZEMARK" button, mic publish, remote-audio playback, status. |
| `.env.example` | Template for `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET`. |

## Pinned dependency versions (verified July 2026)

- `livekit-client` **2.21.0** (browser SDK)
- `livekit-server-sdk` **2.17.0** (token minting; `AccessToken.toJwt()` is async)
- `express` 4.21.2, `cors` 2.8.5, `dotenv` 16.4.7
- `vite` 5.4.11, `concurrently` 9.1.0

## Setup

```bash
cd jarvis/web-client
npm install
cp .env.example .env
# edit .env with your LiveKit project's URL, API key, and secret
```

The `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` **must belong to the
same LiveKit project** the Python `zemark` agent connects to — the agent and the
browser meet inside a room on that one server.

## Run

Run both processes (token server on :3001, Vite on :5173):

```bash
npm run dev
```

Or run them separately in two terminals:

```bash
npm run token-server   # http://localhost:3001
npm run vite           # http://localhost:5173
```

Open <http://localhost:5173>, click **Falar com ZEMARK**, allow the microphone,
and speak. You should hear ZEMARK greet you (the agent calls
`generate_reply(...)` on start).

## How it connects to the Python agent

1. The browser asks the token server for a token
   (`GET /token?room=zemark-room&identity=...`). The token grants `roomJoin`,
   `canPublish`, and `canSubscribe` for that room.
2. The browser connects to the room and publishes its mic.
3. The **`zemark` agent must be dispatched into that room** so it joins, runs
   STT -> ClaudeBrain -> Kokoro TTS, and publishes audio back. The browser
   attaches that remote track and you hear the reply.

### Getting the "zemark" agent into the room

The agent uses **named dispatch** (`agent_name="zemark"`), so it does **not**
auto-join every room. Pick one of:

- **Automatic dispatch** — configure the agent's name in your LiveKit project so
  every new room (or a matching set) dispatches `zemark`. In LiveKit Cloud this
  is set up in the agents/dispatch settings for the deployment.

- **Explicit dispatch** — create the room with an explicit agent dispatch for
  `zemark` before/when the user joins. Server-side (Node `livekit-server-sdk`)
  this is done with `RoomServiceClient` / `AgentDispatchClient` creating a
  dispatch with `agentName: 'zemark'` and the same `roomName` this client uses
  (`zemark-room`). You can extend `server/token-server.js` to do this at token
  time if you want a fully hands-off flow.

Either way, the room name the browser joins (`zemark-room`, set in
`src/main.js`) must be the room the `zemark` agent is dispatched into.

## Notes

- The API **secret never reaches the browser** — only the minted JWT and the
  `wss://` URL do.
- Change the room name in `src/main.js` (`ROOM_NAME`) and, if you add automatic
  dispatch keyed on room name, keep the two in sync.
- Modern browsers require a user gesture before audio playback; connecting is
  driven by the button click, which satisfies that.
