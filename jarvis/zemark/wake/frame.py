"""Frame-based wake detectors (Porcupine, openWakeWord).

These are the "production" wake backends: always-on, low-power, and low-latency
because they score raw 16 kHz PCM frames locally instead of running full STT.
Both need a one-time setup step for a custom word like "ZEMARK":

    * Porcupine    — type "zemark" in the Picovoice console, download the macOS
                     ``.ppn``, set PICOVOICE_ACCESS_KEY + ZEMARK_PORCUPINE_PPN.
    * openWakeWord — train a model in the official Colab notebook, download
                     ``ZEMARK.onnx``, set ZEMARK_OWW_ONNX.

The heavy libraries are imported lazily so importing this module never fails on
a machine that only uses the phrase backend.
"""

from __future__ import annotations

import time
from typing import Protocol

import numpy as np


class FrameWakeDetector(Protocol):
    """Feed consecutive int16 mono 16 kHz frames; returns True on trigger."""

    frame_length: int
    sample_rate: int

    def process(self, pcm_int16: np.ndarray) -> bool: ...

    def close(self) -> None: ...


class _Refractory:
    """Debounce so one utterance fires once."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self._last = 0.0

    def ok(self) -> bool:
        now = time.monotonic()
        if now - self._last >= self.seconds:
            self._last = now
            return True
        return False


class PorcupineWakeDetector:
    """Picovoice Porcupine backend. Best path for a custom word on macOS."""

    def __init__(
        self,
        access_key: str,
        keyword_path: str,
        *,
        sensitivity: float = 0.5,
        refractory_seconds: float = 2.0,
    ):
        import pvporcupine  # lazy

        self._pp = pvporcupine.create(
            access_key=access_key,
            keyword_paths=[keyword_path],
            sensitivities=[sensitivity],
        )
        self.frame_length = self._pp.frame_length
        self.sample_rate = self._pp.sample_rate
        self._refractory = _Refractory(refractory_seconds)

    def process(self, pcm_int16: np.ndarray) -> bool:
        result = self._pp.process(pcm_int16.astype(np.int16))
        if result >= 0 and self._refractory.ok():
            return True
        return False

    def close(self) -> None:
        try:
            self._pp.delete()
        except Exception:
            pass


class OpenWakeWordDetector:
    """openWakeWord backend. Uses the onnx runtime (the one that works on macOS)."""

    frame_length = 1280  # 80 ms @ 16 kHz — openWakeWord's expected frame
    sample_rate = 16000

    def __init__(
        self,
        model_path: str,
        *,
        threshold: float = 0.5,
        refractory_seconds: float = 2.0,
    ):
        from openwakeword.model import Model  # lazy

        self._model = Model(wakeword_models=[model_path], inference_framework="onnx")
        self._threshold = threshold
        self._refractory = _Refractory(refractory_seconds)

    def process(self, pcm_int16: np.ndarray) -> bool:
        scores = self._model.predict(pcm_int16.astype(np.int16))
        best = max(scores.values()) if scores else 0.0
        if best >= self._threshold and self._refractory.ok():
            return True
        return False

    def close(self) -> None:  # openWakeWord holds no OS handles
        pass
