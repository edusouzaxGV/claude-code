// ZEMARK voice web client (frontend).
//
// Flow:
//   1. Fetch a LiveKit token + server URL from the local token server.
//   2. Connect to the room.
//   3. Publish the microphone.
//   4. Attach the agent's remote audio track so the user can hear ZEMARK.
//   5. Reflect connection state in the UI.
//
// Verified against livekit-client 2.21.0 (July 2026):
//   - `new Room(opts)` then `await room.connect(url, token)`
//   - `await room.localParticipant.setMicrophoneEnabled(true)`
//   - `RoomEvent.TrackSubscribed` -> `track.attach()` for remote audio
//   - `RoomEvent.ConnectionStateChanged` with the `ConnectionState` enum
//   - `Track.Kind.Audio` to filter track kinds

import {
  Room,
  RoomEvent,
  Track,
  ConnectionState,
} from 'livekit-client';

// Base URL of the token server. In dev, Vite (5173) and the token server
// (3001) run on different ports; CORS is enabled server-side.
const TOKEN_SERVER = 'http://localhost:3001';

// Room name must be one the "zemark" agent gets dispatched into. See README:
// with automatic dispatch the agent name is configured on the server side; with
// explicit dispatch you create the room with an agent dispatch for "zemark".
const ROOM_NAME = 'zemark-room';

const talkBtn = document.getElementById('talk');
const statusEl = document.getElementById('status');

/** @type {Room | null} */
let room = null;

function setStatus(text, kind = '') {
  statusEl.textContent = text;
  statusEl.className = kind;
}

async function fetchToken() {
  const identity = `web-user-${Math.random().toString(36).slice(2, 8)}`;
  const url = `${TOKEN_SERVER}/token?room=${encodeURIComponent(
    ROOM_NAME,
  )}&identity=${encodeURIComponent(identity)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Token server returned ${res.status}`);
  return res.json(); // { token, url }
}

async function connect() {
  talkBtn.disabled = true;
  setStatus('Conectando...', '');

  try {
    const { token, url } = await fetchToken();

    room = new Room({
      // Let the SDK pick sensible audio capture defaults (echo cancellation,
      // noise suppression) for a voice assistant.
      adaptiveStream: true,
      dynacast: true,
    });

    // --- Remote audio: attach the agent's track so we can hear it. ---
    room.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === Track.Kind.Audio) {
        const el = track.attach(); // creates an <audio> element
        el.autoplay = true;
        document.body.appendChild(el);
      }
    });

    room.on(RoomEvent.TrackUnsubscribed, (track) => {
      track.detach().forEach((el) => el.remove());
    });

    // --- Connection state -> UI. ---
    room.on(RoomEvent.ConnectionStateChanged, (state) => {
      if (state === ConnectionState.Connected) {
        setStatus('Conectado. Pode falar!', 'connected');
      } else if (state === ConnectionState.Reconnecting) {
        setStatus('Reconectando...', '');
      } else if (state === ConnectionState.Disconnected) {
        setStatus('Desconectado.', '');
        talkBtn.disabled = false;
        talkBtn.textContent = 'Falar com ZEMARK';
      }
    });

    room.on(RoomEvent.Disconnected, () => {
      cleanup();
    });

    await room.connect(url, token);

    // Publish the microphone (prompts for mic permission on first use).
    await room.localParticipant.setMicrophoneEnabled(true);

    talkBtn.disabled = false;
    talkBtn.textContent = 'Encerrar';
  } catch (err) {
    console.error(err);
    setStatus(`Erro: ${err.message}`, 'error');
    talkBtn.disabled = false;
    talkBtn.textContent = 'Falar com ZEMARK';
    room = null;
  }
}

function cleanup() {
  room = null;
  talkBtn.disabled = false;
  talkBtn.textContent = 'Falar com ZEMARK';
}

async function disconnect() {
  if (room) await room.disconnect();
}

talkBtn.addEventListener('click', () => {
  // Toggle: connect if idle, disconnect if already in a room.
  if (room && room.state === ConnectionState.Connected) {
    disconnect();
  } else {
    connect();
  }
});
