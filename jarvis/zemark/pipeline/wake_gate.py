"""Wake-word gate for the always-on desktop pipeline.

The mic + STT run continuously, but the *brain* should only answer when
addressed. This processor sits right after STT and decides which transcriptions
are allowed through to the LLM:

    * If a conversation is already open (recent activity), everything passes —
      so follow-ups don't need the wake word again.
    * Otherwise, a transcription passes only if it contains the wake word
      ("ZEMARK"); the wake word is stripped so the remainder is treated as the
      actual command. Saying just "ZEMARK" opens the window and waits.
    * After ``idle_timeout`` seconds of silence the window closes and the wake
      word is required again.

This is the natural fit for an STT-driven pipeline and needs zero setup. The
Porcupine / openWakeWord frame detectors remain available for a low-power
always-listening capture path (see the wake module and README).
"""

from __future__ import annotations

import time

from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from ..wake.phrase import PhraseMatcher


class WakeGate(FrameProcessor):
    def __init__(self, matcher: PhraseMatcher, *, idle_timeout: float = 45.0, on_wake=None):
        super().__init__()
        self._matcher = matcher
        self._idle_timeout = idle_timeout
        self._last_activity = 0.0
        self._on_wake = on_wake  # optional callable() when the window opens

    @property
    def conversation_open(self) -> bool:
        return (time.monotonic() - self._last_activity) < self._idle_timeout

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if not isinstance(frame, TranscriptionFrame):
            await self.push_frame(frame, direction)
            return

        text = (frame.text or "").strip()
        if not text:
            return

        if self.conversation_open:
            self._last_activity = time.monotonic()
            await self.push_frame(frame, direction)
            return

        if self._matcher.matches(text):
            self._last_activity = time.monotonic()
            if self._on_wake is not None:
                self._on_wake()
            remainder = self._matcher.strip_wake(text)
            if remainder:
                await self.push_frame(_retext(frame, remainder), direction)
            # bare "ZEMARK" with no command: window is open, wait for the next turn
            return

        # not addressed to ZEMARK — drop it
        return

    def touch(self) -> None:
        """Externally mark activity (e.g. right after a proactive utterance)."""
        self._last_activity = time.monotonic()


def _retext(frame: TranscriptionFrame, text: str) -> TranscriptionFrame:
    """Clone a TranscriptionFrame with replaced text, tolerating API drift."""
    user_id = getattr(frame, "user_id", "")
    timestamp = getattr(frame, "timestamp", "")
    try:
        return TranscriptionFrame(text, user_id, timestamp)
    except TypeError:  # pragma: no cover - signature drift
        new = TranscriptionFrame(text=text)  # type: ignore[call-arg]
        return new
