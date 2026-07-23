"""ZEMARK — a genuinely good, free, self-hosted Jarvis.

Layers:
    config      — env-driven, swappable providers
    persona     — the ZEMARK voice/personality + system-prompt builder
    brain       — Claude Agent SDK reasoning engine (subscription auth)
    stt / tts   — Pipecat speech services (Groq/Whisper, Kokoro)
    wake        — pluggable "ZEMARK" wake detection
    memory      — persistent store + auto-learning reflection
    proactive   — the loop that lets ZEMARK speak first
    pipeline    — desktop (Pipecat) voice agent assembly
    livekit_agent — web/phone front-end sharing the same brain
"""

from __future__ import annotations

__version__ = "0.1.0"

from .config import Config, load_config
from .memory.store import MemoryStore
from .persona import build_system_prompt

__all__ = ["Config", "load_config", "MemoryStore", "build_system_prompt", "__version__"]
