"""Central configuration for ZEMARK.

Everything is driven by environment variables so the whole stack is swappable
without touching code. Load order: process env > a local `.env` (if python-dotenv
is installed) > the defaults below.

Design goals:
    * Zero required paid API keys. The brain runs on a Claude Pro/Max
      *subscription* via the Claude Agent SDK; STT/TTS default to free options.
    * Sensible, low-latency defaults tuned for Mac Apple Silicon.
    * Every provider choice is a plain string so you can flip it in `.env`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# .env loading (optional dependency)
# ---------------------------------------------------------------------------
try:  # pragma: no cover - trivial
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# Root of the jarvis/ project (…/jarvis)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(_env("ZEMARK_DATA_DIR", str(PROJECT_ROOT / "data")))
MODELS_DIR = Path(_env("ZEMARK_MODELS_DIR", str(PROJECT_ROOT / "models")))


@dataclass(frozen=True)
class BrainConfig:
    """The reasoning engine (Claude Agent SDK, subscription auth)."""

    # "sonnet" is the latency/quality sweet spot for a voice loop; "haiku" is
    # snappier, "opus" is smartest but slower. Full ids also accepted.
    model: str = _env("ZEMARK_BRAIN_MODEL", "sonnet")
    # Keep spoken replies short by default — this is injected into the persona.
    max_reply_sentences: int = _env_int("ZEMARK_MAX_REPLY_SENTENCES", 3)
    # "bypassPermissions" so the voice loop never blocks on an interactive
    # permission prompt. Tools are still gated by the allow-list.
    permission_mode: str = _env("ZEMARK_PERMISSION_MODE", "bypassPermissions")
    # If true, the launcher strips ANTHROPIC_API_KEY from the environment so the
    # subscription OAuth token is actually used (the API key otherwise wins and
    # silently bills you). Turn off only if you *want* to pay per token.
    force_subscription_auth: bool = _env_bool("ZEMARK_FORCE_SUBSCRIPTION_AUTH", True)


@dataclass(frozen=True)
class STTConfig:
    """Speech-to-text. 'groq' (free tier, fast) or 'whisper' (local, private)."""

    provider: str = _env("ZEMARK_STT_PROVIDER", "groq")
    groq_model: str = _env("ZEMARK_STT_GROQ_MODEL", "whisper-large-v3-turbo")
    # Local faster-whisper. On Apple Silicon CTranslate2 is CPU-only; int8 is
    # the best speed/memory tradeoff. Use a smaller model for lower latency.
    whisper_model: str = _env("ZEMARK_STT_WHISPER_MODEL", "small")
    whisper_device: str = _env("ZEMARK_STT_WHISPER_DEVICE", "cpu")
    whisper_compute_type: str = _env("ZEMARK_STT_WHISPER_COMPUTE", "int8")
    language: str = _env("ZEMARK_STT_LANGUAGE", "pt")


@dataclass(frozen=True)
class TTSConfig:
    """Text-to-speech via Kokoro (local, free, ~24kHz). pt-br by default."""

    provider: str = _env("ZEMARK_TTS_PROVIDER", "kokoro")
    # Kokoro voice + language. 'pf_dora' is a Brazilian-Portuguese female voice;
    # 'af_heart' is the flagship English one. Voice must match the language.
    voice: str = _env("ZEMARK_TTS_VOICE", "pf_dora")
    language: str = _env("ZEMARK_TTS_LANGUAGE", "pt-br")
    speed: float = _env_float("ZEMARK_TTS_SPEED", 1.0)
    sample_rate: int = _env_int("ZEMARK_TTS_SAMPLE_RATE", 24000)


@dataclass(frozen=True)
class WakeConfig:
    """Wake-word gate. Default backend works on day one with no training."""

    # "stt_phrase" (no setup) | "porcupine" (.ppn) | "openwakeword" (.onnx)
    backend: str = _env("ZEMARK_WAKE_BACKEND", "stt_phrase")
    word: str = _env("ZEMARK_WAKE_WORD", "zemark")
    # Alternate spellings the STT-phrase backend also accepts (STT often mangles
    # a made-up word). Comma-separated in the env.
    aliases: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            a.strip().lower()
            for a in _env(
                "ZEMARK_WAKE_ALIASES",
                "zemark,ze mark,zé mark,zi mark,zemarki,zemarck,z mark",
            ).split(",")
            if a.strip()
        )
    )
    threshold: float = _env_float("ZEMARK_WAKE_THRESHOLD", 0.5)
    porcupine_model_path: str | None = _env("ZEMARK_PORCUPINE_PPN")
    porcupine_access_key: str | None = _env("PICOVOICE_ACCESS_KEY")
    openwakeword_model_path: str | None = _env("ZEMARK_OWW_ONNX")
    # After a trigger, ignore further triggers for this many seconds.
    refractory_seconds: float = _env_float("ZEMARK_WAKE_REFRACTORY", 2.0)


@dataclass(frozen=True)
class MemoryConfig:
    """Persistent, self-updating memory."""

    db_path: str = _env("ZEMARK_MEMORY_DB", str(DATA_DIR / "memory.sqlite3"))
    # Run the reflection/auto-learn pass after each conversation ends.
    auto_learn: bool = _env_bool("ZEMARK_AUTO_LEARN", True)
    # How many memories to surface into context on each turn.
    recall_limit: int = _env_int("ZEMARK_RECALL_LIMIT", 6)
    # Minimum confidence for an auto-learned fact to be stored.
    min_confidence: float = _env_float("ZEMARK_MEMORY_MIN_CONFIDENCE", 0.55)


@dataclass(frozen=True)
class ProactiveConfig:
    """The loop that lets ZEMARK speak first."""

    enabled: bool = _env_bool("ZEMARK_PROACTIVE", True)
    # How often the proactive engine evaluates its triggers, in seconds.
    tick_seconds: float = _env_float("ZEMARK_PROACTIVE_TICK", 30.0)
    # Don't interrupt more often than this, in seconds (anti-nag guard).
    min_gap_seconds: float = _env_float("ZEMARK_PROACTIVE_MIN_GAP", 600.0)
    # Quiet hours (local 24h clock). ZEMARK stays silent between these.
    quiet_start_hour: int = _env_int("ZEMARK_QUIET_START", 23)
    quiet_end_hour: int = _env_int("ZEMARK_QUIET_END", 8)


@dataclass(frozen=True)
class AudioConfig:
    """Microphone / playback settings shared across the pipeline."""

    input_sample_rate: int = _env_int("ZEMARK_AUDIO_IN_RATE", 16000)
    output_sample_rate: int = _env_int("ZEMARK_AUDIO_OUT_RATE", 24000)
    # End the active conversation after this many seconds of silence, dropping
    # back to wake-word listening.
    conversation_idle_timeout: float = _env_float("ZEMARK_IDLE_TIMEOUT", 45.0)


@dataclass(frozen=True)
class Config:
    brain: BrainConfig = field(default_factory=BrainConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    wake: WakeConfig = field(default_factory=WakeConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    proactive: ProactiveConfig = field(default_factory=ProactiveConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)

    # Free-tier keys (optional). None means "not configured".
    groq_api_key: str | None = _env("GROQ_API_KEY")
    user_name: str = _env("ZEMARK_USER_NAME", "chefe")
    assistant_name: str = _env("ZEMARK_ASSISTANT_NAME", "ZEMARK")

    def ensure_dirs(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        Path(self.memory.db_path).parent.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    """Build the config from the current environment and ensure data dirs."""
    cfg = Config()
    cfg.ensure_dirs()
    return cfg
