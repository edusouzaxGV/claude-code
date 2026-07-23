"""LiveKit voice agent — the browser/phone front-end.

Shares ZEMARK's brain, memory, and voice with the desktop app by wrapping the
same :class:`ClaudeBrain` behind a LiveKit ``llm.LLM`` and Kokoro behind a
LiveKit ``tts.TTS``. The desktop and web front-ends are therefore just two
transports over one assistant.

This targets the LiveKit Agents 1.6 API (``AgentServer`` + ``@server.rtc_session``,
custom STT/LLM/TTS subclasses, Silero VAD + turn detector). It is the most
version-sensitive file in the project; if you upgrade the SDK, verify the
custom base-class internals against the installed plugin source (openai/cartesia
plugins are the canonical examples).

Run:
    export CLAUDE_CODE_OAUTH_TOKEN=...   # subscription auth (see README)
    export GROQ_API_KEY=...              # STT plugin
    export LIVEKIT_URL/LIVEKIT_API_KEY/LIVEKIT_API_SECRET=...
    python -m zemark.livekit_agent console   # or: dev / start

Model files for Kokoro (downloaded once, see README):
    ZEMARK_KOKORO_ONNX   (default: models/kokoro-v1.0.onnx)
    ZEMARK_KOKORO_VOICES (default: models/voices-v1.0.bin)
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import numpy as np

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli
from livekit.agents.llm import LLM, ChatChunk, ChatContext, ChoiceDelta, LLMStream
from livekit.agents.tts import TTS, ChunkedStream, TTSCapabilities
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions
from livekit.plugins import silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from .brain.claude_brain import ClaudeBrain
from .config import Config, load_config
from .memory.store import MemoryStore
from .persona import build_system_prompt
from .tools.builtin import build_tool_server

_KOKORO_SR = 24000


# --------------------------------------------------------------------------
# Shared-brain LLM
# --------------------------------------------------------------------------
class ClaudeBrainLLM(LLM):
    def __init__(self, brain: ClaudeBrain, store: MemoryStore, cfg: Config):
        super().__init__()
        self._brain = brain
        self._store = store
        self._cfg = cfg

    def chat(self, *, chat_ctx: ChatContext, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS,
             parallel_tool_calls=None, tool_choice=None, extra_kwargs=None) -> "_ClaudeStream":
        return _ClaudeStream(self, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options,
                             brain=self._brain, store=self._store, cfg=self._cfg)


class _ClaudeStream(LLMStream):
    def __init__(self, llm, *, chat_ctx, tools, conn_options, brain, store, cfg):
        super().__init__(llm, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)
        self._brain = brain
        self._store = store
        self._cfg = cfg

    async def _run(self) -> None:
        user_text = _last_user_text(self._chat_ctx)
        if not user_text:
            return
        self._store.log_turn("user", user_text)
        memories = [m.text for m in self._store.recall(user_text, limit=self._cfg.memory.recall_limit)]
        reply: list[str] = []
        async for chunk in self._brain.ask(user_text, memories):
            reply.append(chunk)
            self._event_ch.send_nowait(
                ChatChunk(id="zemark", delta=ChoiceDelta(role="assistant", content=chunk))
            )
        text = "".join(reply).strip()
        if text:
            self._store.log_turn("assistant", text)


def _last_user_text(chat_ctx: ChatContext) -> str:
    items = getattr(chat_ctx, "items", None) or getattr(chat_ctx, "messages", [])
    for item in reversed(list(items)):
        if getattr(item, "role", "") != "user":
            continue
        content = getattr(item, "content", None) or getattr(item, "text_content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return " ".join(str(c) for c in content).strip()
    return ""


# --------------------------------------------------------------------------
# Kokoro TTS (shared voice)
# --------------------------------------------------------------------------
class KokoroLiveKitTTS(TTS):
    def __init__(self, voice: str = "pf_dora", lang: str = "pt-br", speed: float = 1.0):
        super().__init__(
            capabilities=TTSCapabilities(streaming=False),
            sample_rate=_KOKORO_SR,
            num_channels=1,
        )
        from kokoro_onnx import Kokoro  # lazy

        onnx = os.getenv("ZEMARK_KOKORO_ONNX", "models/kokoro-v1.0.onnx")
        voices = os.getenv("ZEMARK_KOKORO_VOICES", "models/voices-v1.0.bin")
        self._kokoro = Kokoro(onnx, voices)
        self._voice, self._lang, self._speed = voice, lang, speed

    def synthesize(self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS):
        return _KokoroChunked(self, text, conn_options=conn_options,
                              kokoro=self._kokoro, voice=self._voice, lang=self._lang, speed=self._speed)


class _KokoroChunked(ChunkedStream):
    def __init__(self, tts, text, *, conn_options, kokoro, voice, lang, speed):
        super().__init__(tts=tts, input_text=text, conn_options=conn_options)
        self._kokoro = kokoro
        self._voice, self._lang, self._speed = voice, lang, speed

    async def _run(self, output_emitter) -> None:
        output_emitter.initialize(
            request_id="zemark-tts",
            sample_rate=_KOKORO_SR,
            num_channels=1,
            mime_type="audio/pcm",
        )
        stream = self._kokoro.create_stream(
            self._input_text, voice=self._voice, lang=self._lang, speed=self._speed
        )
        async for samples, _sr in stream:
            pcm = (np.asarray(samples) * 32767).astype(np.int16).tobytes()
            output_emitter.push(pcm)
        output_emitter.flush()


# --------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------
server = AgentServer()


class ZemarkAssistant(Agent):
    def __init__(self, cfg: Config, memories: list[str]):
        super().__init__(instructions=build_system_prompt(cfg, memories=memories))


@server.rtc_session(agent_name="zemark")
async def entrypoint(ctx: JobContext) -> None:
    cfg = load_config()
    store = MemoryStore(cfg.memory.db_path)

    from .reminders import ReminderStore

    reminders = ReminderStore(cfg.memory.db_path)
    tool_server, allowed = build_tool_server(store, reminders)
    brain = ClaudeBrain(cfg, tool_server=tool_server, allowed_tools=allowed)
    await brain.start()

    stt = _build_livekit_stt(cfg)
    session = AgentSession(
        stt=stt,
        llm=ClaudeBrainLLM(brain, store, cfg),
        tts=KokoroLiveKitTTS(voice=cfg.tts.voice, lang=cfg.tts.language, speed=cfg.tts.speed),
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
    )
    memories = [m.text for m in store.recent(limit=cfg.memory.recall_limit)]
    await session.start(room=ctx.room, agent=ZemarkAssistant(cfg, memories))
    await ctx.connect()
    await session.generate_reply(instructions="Cumprimente brevemente e se ofereça para ajudar.")


def _build_livekit_stt(cfg: Config):
    """Use the Groq Whisper plugin for STT (free tier)."""
    if not cfg.groq_api_key:
        raise ValueError(
            "The LiveKit path needs GROQ_API_KEY for STT (free at console.groq.com). "
            "The desktop path can run STT fully local instead."
        )
    from livekit.plugins import groq  # lazy

    return groq.STT(model=cfg.stt.groq_model)


def main() -> None:
    cli.run_app(server)


if __name__ == "__main__":
    main()
