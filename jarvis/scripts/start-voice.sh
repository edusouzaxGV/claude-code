#!/usr/bin/env bash
# ZEMARK — one command to launch the full voice + HUD experience.
#
# Starts the LiveKit voice agent (brain + STT + Kokoro TTS) and the browser HUD
# (token server + Vite), then opens http://localhost:5173. Ctrl+C stops both.
#
#   ./scripts/start-voice.sh
#
# Reads credentials from jarvis/.env (git-ignored). Required there:
#   CLAUDE_CODE_OAUTH_TOKEN   (run `claude setup-token`)
#   GROQ_API_KEY              (free at console.groq.com)
#   LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET  (livekit.io)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
PY="${PYTHON:-python3}"

# --- load .env --------------------------------------------------------------
if [[ ! -f .env ]]; then
  echo "✗ Falta jarvis/.env. Copie de .env.example e preencha." >&2
  exit 1
fi
set -a; . ./.env; set +a
unset ANTHROPIC_API_KEY || true   # never let a paid key override the subscription

# --- validate credentials ---------------------------------------------------
missing=()
for v in CLAUDE_CODE_OAUTH_TOKEN GROQ_API_KEY LIVEKIT_URL LIVEKIT_API_KEY LIVEKIT_API_SECRET; do
  [[ -z "${!v:-}" ]] && missing+=("$v")
done
if (( ${#missing[@]} )); then
  echo "✗ Faltam credenciais no .env: ${missing[*]}" >&2
  echo "  • CLAUDE_CODE_OAUTH_TOKEN  -> claude setup-token" >&2
  echo "  • GROQ_API_KEY             -> console.groq.com (grátis)" >&2
  exit 1
fi

# --- Kokoro voice model (auto-download if missing) --------------------------
ONNX="${ZEMARK_KOKORO_ONNX:-models/kokoro-v1.0.onnx}"
VOICES="${ZEMARK_KOKORO_VOICES:-models/voices-v1.0.bin}"
REL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
mkdir -p "$(dirname "$ONNX")"
if [[ ! -f "$ONNX" ]]; then
  echo "· baixando modelo de voz Kokoro (~300MB, uma vez só)…"
  curl -fL "$REL/kokoro-v1.0.onnx" -o "$ONNX"
fi
if [[ ! -f "$VOICES" ]]; then
  echo "· baixando vozes Kokoro…"
  curl -fL "$REL/voices-v1.0.bin" -o "$VOICES"
fi

# --- web-client env ---------------------------------------------------------
if [[ ! -f web-client/.env ]]; then
  printf 'LIVEKIT_URL=%s\nLIVEKIT_API_KEY=%s\nLIVEKIT_API_SECRET=%s\n' \
    "$LIVEKIT_URL" "$LIVEKIT_API_KEY" "$LIVEKIT_API_SECRET" > web-client/.env
fi

# --- start the agent --------------------------------------------------------
AGENT_LOG="$(mktemp -t zemark-agent.XXXXXX.log)"
echo "· iniciando o agente ZEMARK (log: $AGENT_LOG)…"
"$PY" run.py livekit dev >"$AGENT_LOG" 2>&1 &
AGENT_PID=$!

cleanup() {
  echo; echo "· encerrando…"
  kill "$AGENT_PID" 2>/dev/null || true
  [[ -n "${WEB_PID:-}" ]] && kill "$WEB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# give the worker a moment to register with LiveKit
sleep 3
if ! kill -0 "$AGENT_PID" 2>/dev/null; then
  echo "✗ O agente não subiu. Últimas linhas do log:" >&2
  tail -n 20 "$AGENT_LOG" >&2
  exit 1
fi

# --- start the HUD ----------------------------------------------------------
cd web-client
if [[ ! -d node_modules ]]; then
  echo "· instalando dependências do HUD (npm install)…"
  npm install
fi
echo "· iniciando o HUD…"
npm run dev &
WEB_PID=$!

# open the browser once Vite is up
( sleep 4
  URL="http://localhost:5173"
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  fi
  echo; echo "🛰️  ZEMARK pronto em $URL — clique INICIAR e fale." ) &

wait "$WEB_PID"
