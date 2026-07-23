// ZEMARK voice web client — connects to the LiveKit "zemark" agent and drives
// the J.A.R.V.I.S.-style HUD from live audio.
//
// Flow:
//   1. Fetch a LiveKit token + server URL from the local token server.
//   2. Connect to the room, publish the mic, attach the agent's audio.
//   3. Tap both audio streams into Web Audio analysers and feed the HUD.
//   4. Map active-speaker changes to HUD states (listening / thinking / speaking).
//
// Verified against livekit-client 2.21.0 (July 2026).

import { Room, RoomEvent, Track, ConnectionState } from 'livekit-client';
import { ZemarkHUD } from './hud.js';

const TOKEN_SERVER = 'http://localhost:3001';
const ROOM_NAME = 'zemark-room';

const talkBtn = document.getElementById('talk');
const statusEl = document.getElementById('status');
const stateLabel = document.getElementById('state-label');
const hudEl = document.querySelector('.hud');
const transcriptEl = document.getElementById('transcript');

const hud = new ZemarkHUD(document.getElementById('reactor'));
hud.start();

/** @type {Room | null} */
let room = null;
/** @type {AudioContext | null} */
let audioCtx = null;
let sawLocalSpeech = false;

const STATE_LABELS = {
  idle: 'EM ESPERA',
  listening: 'OUVINDO',
  thinking: 'PROCESSANDO',
  speaking: 'FALANDO',
};

function setHudState(state) {
  hud.setState(state);
  hudEl.dataset.state = state;
  if (stateLabel) stateLabel.textContent = STATE_LABELS[state] || '';
}

function setStatus(text, kind = '') {
  statusEl.textContent = text;
  statusEl.className = `status ${kind}`;
}

function makeAnalyser(mediaStreamTrack) {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const src = audioCtx.createMediaStreamSource(new MediaStream([mediaStreamTrack]));
  const an = audioCtx.createAnalyser();
  an.fftSize = 512;
  an.smoothingTimeConstant = 0.82;
  src.connect(an); // tap only — not connected to destination (no echo)
  return an;
}

async function fetchToken() {
  const identity = `web-user-${Math.random().toString(36).slice(2, 8)}`;
  const url = `${TOKEN_SERVER}/token?room=${encodeURIComponent(ROOM_NAME)}&identity=${encodeURIComponent(identity)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Token server ${res.status}`);
  return res.json(); // { token, url }
}

function wireSpeakers() {
  room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
    const agentSpeaking = speakers.some((p) => p !== room.localParticipant);
    const localSpeaking = speakers.some((p) => p === room.localParticipant);
    if (agentSpeaking) {
      setHudState('speaking');
      sawLocalSpeech = false;
    } else if (localSpeaking) {
      setHudState('listening');
      sawLocalSpeech = true;
    } else if (sawLocalSpeech) {
      // user just finished; agent hasn't started yet -> thinking
      setHudState('thinking');
      sawLocalSpeech = false;
    } else if (room.state === ConnectionState.Connected) {
      setHudState('listening');
    }
  });

  // Optional: live transcription, if the agent publishes it.
  if (RoomEvent.TranscriptionReceived) {
    room.on(RoomEvent.TranscriptionReceived, (segments) => {
      const last = segments[segments.length - 1];
      if (last && transcriptEl) transcriptEl.textContent = last.text;
    });
  }
}

async function connect() {
  talkBtn.disabled = true;
  setStatus('Conectando…');
  setHudState('thinking');

  try {
    const { token, url } = await fetchToken();
    room = new Room({ adaptiveStream: true, dynacast: true });

    room.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === Track.Kind.Audio) {
        const el = track.attach();
        el.autoplay = true;
        document.body.appendChild(el);
        // tap the agent's voice into the HUD
        if (track.mediaStreamTrack) hud.setAnalyser('agent', makeAnalyser(track.mediaStreamTrack));
      }
    });

    room.on(RoomEvent.TrackUnsubscribed, (track) => {
      track.detach().forEach((el) => el.remove());
    });

    room.on(RoomEvent.ConnectionStateChanged, (state) => {
      if (state === ConnectionState.Connected) {
        setStatus('Conectado. Pode falar!', 'connected');
        setHudState('listening');
      } else if (state === ConnectionState.Reconnecting) {
        setStatus('Reconectando…');
        setHudState('thinking');
      } else if (state === ConnectionState.Disconnected) {
        setStatus('Desconectado.');
        setHudState('idle');
        talkBtn.disabled = false;
        talkBtn.textContent = 'INICIAR';
      }
    });

    room.on(RoomEvent.Disconnected, cleanup);

    wireSpeakers();

    await room.connect(url, token);
    await room.localParticipant.setMicrophoneEnabled(true);

    // tap the local mic into the HUD
    const pub = room.localParticipant.getTrackPublication?.(Track.Source.Microphone);
    const micTrack = pub?.track?.mediaStreamTrack;
    if (micTrack) hud.setAnalyser('mic', makeAnalyser(micTrack));
    if (audioCtx && audioCtx.state === 'suspended') await audioCtx.resume();

    talkBtn.disabled = false;
    talkBtn.textContent = 'ENCERRAR';
  } catch (err) {
    console.error(err);
    setStatus(`Erro: ${err.message}`, 'error');
    setHudState('idle');
    talkBtn.disabled = false;
    talkBtn.textContent = 'INICIAR';
    room = null;
  }
}

function cleanup() {
  room = null;
  setHudState('idle');
  talkBtn.disabled = false;
  talkBtn.textContent = 'INICIAR';
}

async function disconnect() {
  if (room) await room.disconnect();
}

talkBtn.addEventListener('click', () => {
  if (room && room.state === ConnectionState.Connected) disconnect();
  else connect();
});
