"""Build the configured wake backend.

Returns either a :class:`PhraseMatcher` (text-based, default) or a
:class:`FrameWakeDetector` (audio-frame based). The app layer inspects the
type to decide how to drive it.
"""

from __future__ import annotations

from ..config import WakeConfig
from .phrase import PhraseMatcher


def build_wake(cfg: WakeConfig):
    backend = cfg.backend.lower()

    if backend == "stt_phrase":
        return PhraseMatcher(word=cfg.word, aliases=cfg.aliases, fuzzy_threshold=cfg.threshold + 0.32)

    if backend == "porcupine":
        if not cfg.porcupine_access_key or not cfg.porcupine_model_path:
            raise ValueError(
                "Porcupine backend needs PICOVOICE_ACCESS_KEY and ZEMARK_PORCUPINE_PPN. "
                "Falling back is available by setting ZEMARK_WAKE_BACKEND=stt_phrase."
            )
        from .frame import PorcupineWakeDetector

        return PorcupineWakeDetector(
            access_key=cfg.porcupine_access_key,
            keyword_path=cfg.porcupine_model_path,
            sensitivity=cfg.threshold,
            refractory_seconds=cfg.refractory_seconds,
        )

    if backend == "openwakeword":
        if not cfg.openwakeword_model_path:
            raise ValueError(
                "openWakeWord backend needs ZEMARK_OWW_ONNX pointing at a trained .onnx model."
            )
        from .frame import OpenWakeWordDetector

        return OpenWakeWordDetector(
            model_path=cfg.openwakeword_model_path,
            threshold=cfg.threshold,
            refractory_seconds=cfg.refractory_seconds,
        )

    raise ValueError(f"Unknown wake backend: {cfg.backend!r}")
