"""Build the configured Pipecat STT service.

Both backends ship with Pipecat, so this is thin glue:
    * ``groq``    — GroqSTTService (free tier, ~real-time, needs GROQ_API_KEY).
    * ``whisper`` — WhisperSTTService (faster-whisper, fully local; CPU/int8 on
                    Apple Silicon).

Imports are lazy so the module loads without the audio extras installed.
"""

from __future__ import annotations

from ..config import Config


def build_stt(cfg: Config):
    provider = cfg.stt.provider.lower()

    if provider == "groq":
        if not cfg.groq_api_key:
            raise ValueError(
                "STT provider 'groq' needs GROQ_API_KEY (free, no card at console.groq.com). "
                "Or set ZEMARK_STT_PROVIDER=whisper to run fully local."
            )
        from pipecat.services.groq.stt import GroqSTTService

        return GroqSTTService(api_key=cfg.groq_api_key, model=cfg.stt.groq_model)

    if provider == "whisper":
        from pipecat.services.whisper.stt import WhisperSTTService

        return WhisperSTTService(
            model=cfg.stt.whisper_model,
            device=cfg.stt.whisper_device,
            compute_type=cfg.stt.whisper_compute_type,
        )

    raise ValueError(f"Unknown STT provider: {cfg.stt.provider!r}")
