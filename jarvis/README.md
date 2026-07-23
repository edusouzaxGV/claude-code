# ZEMARK — a genuinely good, free, self-hosted Jarvis

ZEMARK is a voice assistant built the way the good ones are built: streaming
audio, real barge-in, tool-calling that *does* things, persistent memory that
updates itself, and a proactive loop that lets it speak first. It runs on your
**Claude Pro/Max subscription** (no paid API key), a **local Kokoro voice**, and
**free-tier speech-to-text** — so a serious assistant costs effectively nothing.

Wake word: **“ZEMARK”**. Tuned for **Mac Apple Silicon** and Brazilian
Portuguese out of the box (everything is configurable).

> Built as a self-contained subproject. The pure-Python core (config, memory,
> wake matching, persona, proactivity) has no heavy dependencies and is fully
> unit-tested; the voice stack is an optional install.

---

## Why this isn't mediocre

The research behind the design (GitHub, YouTube, Reddit/X) agreed on what
separates a real Jarvis from a toy. ZEMARK does all of it:

| Trait | How ZEMARK does it |
|---|---|
| **Low latency** | Groq Whisper STT (free, ~real-time) + streamed LLM text → TTS starts speaking on the first sentence. Kokoro runs 10×+ real-time on Apple Silicon. |
| **Streaming, not record-then-respond** | Pipecat pipeline streams audio both ways. |
| **Barge-in / interruption** | Silero VAD on the user aggregator → interruptions are automatic. |
| **Tool calling** | In-process MCP tools — time, memory, **reminders with time** ("me lembra às 15h"), **weather** (wttr.in, no key), **media control** (Music/Spotify), open URL/app, notify — plus Claude Code's built-in `WebSearch`/`WebFetch`. |
| **Persistent memory** | Local SQLite + FTS5. `remember` / `recall` / `forget`. |
| **Auto-learning** | After each conversation a reflection pass distils durable facts about you and reinforces them — it gets to know you over time. |
| **Proactive** | A background loop with tasteful triggers lets ZEMARK open the conversation — due **reminders** (delivered on time, even in quiet hours), morning check-in, loose follow-up threads, an evening summary, project nudges — with quiet-hours and anti-nag guards. |
| **Custom wake word** | “ZEMARK” via a zero-setup phrase gate, upgradable to Porcupine or openWakeWord. |

---

## Architecture

```
                 ┌─────────────── desktop (Pipecat) ───────────────┐
  mic ──▶ STT ──▶ WakeGate ──▶ user-agg(VAD) ──▶  BRAIN  ──▶ TTS ──▶ speaker
        (Groq/Whisper)  │  "ZEMARK" gate      (Claude Agent SDK)  (Kokoro, pt-br)
                        │                          │  ▲
                        │                          │  └── in-process tools + web
                        ▼                          ▼
                  ProactiveEngine ◀──────────  MemoryStore (SQLite+FTS5)
                  (speaks first)                   ▲
                                                   └── ReflectionEngine (auto-learn)

  The SAME brain + memory + Kokoro voice also power a browser/phone client via
  LiveKit (zemark/livekit_agent.py) — two transports over one assistant.
```

Everything is swappable via environment variables — see `.env.example`.

---

## Setup (Mac Apple Silicon)

### 1. System deps
```bash
brew install portaudio espeak-ng      # audio I/O + Kokoro G2P fallback
```

### 2. Python env + install
```bash
cd jarvis
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[voice,dev]"         # core + desktop voice stack + test tools
cp .env.example .env
```

### 3. Subscription auth (the brain, no API key)
```bash
npm install -g @anthropic-ai/claude-code   # once, for the token command
claude setup-token                          # sign in; prints an OAuth token
# put it in .env:
#   CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
```
> ⚠️ If `ANTHROPIC_API_KEY` is set anywhere it **silently overrides** the
> subscription token and bills you. ZEMARK strips it automatically
> (`ZEMARK_FORCE_SUBSCRIPTION_AUTH=1`).

### 4. Free speech-to-text key (optional but recommended)
Grab a free Groq key (no credit card) at <https://console.groq.com> → `GROQ_API_KEY` in `.env`.
Prefer fully local? Set `ZEMARK_STT_PROVIDER=whisper` and skip the key.

### 5. Check + run
```bash
python run.py doctor     # verifies auth, keys, config
python run.py            # start ZEMARK — say "ZEMARK" to talk (Ctrl+C to quit)
```

---

## Using it

- Say **“ZEMARK”** to open a conversation window; follow-ups don't need the word
  again until it goes idle (`ZEMARK_IDLE_TIMEOUT`, default 45 s).
- **“ZEMARK, que horas são?”**, **“…procura o clima em São Paulo”**,
  **“…lembra que eu prefiro respostas curtas”**, **“…abre o YouTube”**.
- Inspect what it has learned: `python run.py memory`.

---

## The web / phone interface (LiveKit)

The same brain, memory, and Kokoro voice, exposed to a browser or phone.

```bash
pip install -e ".[livekit]"
# download the Kokoro model files once (see kokoro-onnx releases):
#   models/kokoro-v1.0.onnx , models/voices-v1.0.bin
# set LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET (and GROQ_API_KEY) in .env
python run.py livekit console     # local test; or: dev / start
```
Front-end: either scaffold with `lk app create --template agent-starter-react`
(set `agentName` to `zemark`), or use the minimal bundled client in
[`web-client/`](web-client/README.md) — a tiny token server + `livekit-client`
page with a “Falar com ZEMARK” button.

---

## Wake word backends

| Backend | Setup | When |
|---|---|---|
| `stt_phrase` (default) | none | Works on day one. Fuzzy-matches “ZEMARK” (and aliases) in the transcript. |
| `porcupine` | Type “zemark” in the [Picovoice console](https://picovoice.ai/), download the macOS `.ppn`, set `PICOVOICE_ACCESS_KEY` + `ZEMARK_PORCUPINE_PPN`. `pip install -e ".[wake]"` | Low-power, always-listening, native. |
| `openwakeword` | Train `ZEMARK.onnx` in the official Colab notebook, set `ZEMARK_OWW_ONNX`. `pip install -e ".[wake]"` | Fully open + local. |

Select with `ZEMARK_WAKE_BACKEND`. The desktop pipeline always phrase-gates the
STT stream; the frame backends target a low-power capture path. Full setup +
tuning walkthrough: [`docs/wake-training.md`](docs/wake-training.md). Tune a
trained model live with `python scripts/test_wake.py`.

---

## Configuration

Every knob lives in `.env` (documented in `.env.example`): brain model, STT/TTS
provider + voice, wake word + aliases, memory limits, proactivity cadence +
quiet hours, audio rates. Sensible defaults throughout.

---

## Development

```bash
pip install -e ".[dev]"
python -m pytest         # 49 tests: config, persona, wake matching, memory,
                         # reflection (auto-learn), proactivity
```
The tests cover the pure-Python core and need no audio hardware or API keys.

---

## Cost

Effectively **zero**: brain on your existing Claude subscription, Kokoro TTS
local, STT on Groq's free tier (or fully local Whisper). No per-token API bill.

## Notes & caveats

- Subscription auth is for **personal, single-user** use (Anthropic terms). For
  multi-user/production, switch to `ANTHROPIC_API_KEY`.
- Pin `pipecat-ai==1.6.*` — the desktop pipeline uses the 1.6 API. If you
  upgrade and imports shift, `zemark/pipeline/desktop.py` and
  `zemark/livekit_agent.py` are the only version-sensitive files.
- `faster-whisper` on Apple Silicon is CPU-only; use a small model, or Groq.
