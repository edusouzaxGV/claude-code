"""Build the configured Pipecat TTS service.

Kokoro is the default: local, free, ~24 kHz, fast on Apple Silicon, and it has
Brazilian-Portuguese voices. Pipecat ships ``KokoroTTSService`` (built on
kokoro-onnx) and auto-downloads the model on first run.

Imports are lazy so this module loads without the audio extras installed.
"""

from __future__ import annotations

from ..config import Config


def build_tts(cfg: Config):
    provider = cfg.tts.provider.lower()

    if provider == "kokoro":
        from pipecat.services.kokoro.tts import KokoroTTSService

        try:
            params = KokoroTTSService.InputParams(language=cfg.tts.language)
        except Exception:
            params = None  # older/newer signature — fall back to defaults

        kwargs = dict(voice=cfg.tts.voice, sample_rate=cfg.tts.sample_rate)
        if params is not None:
            kwargs["params"] = params
        return KokoroTTSService(**kwargs)

    raise ValueError(
        f"Unknown TTS provider: {cfg.tts.provider!r}. Supported: 'kokoro'. "
        "ElevenLabs/Cartesia can be added here if you get a key."
    )
