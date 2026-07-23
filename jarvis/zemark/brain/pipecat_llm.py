"""Pipecat ``LLMService`` that speaks through :class:`ClaudeBrain`.

This is the seam between Pipecat's frame pipeline and ZEMARK's brain. On each
completed user turn it:
    1. pulls the latest user utterance from the pipeline context,
    2. recalls relevant long-term memories,
    3. streams the brain's reply into the pipeline as ``LLMTextFrame``s (so TTS
       starts speaking immediately),
    4. logs both sides of the turn for the auto-learning reflection pass.

Pipecat 1.6 API (see the pipeline module for the version note). Imported only
where the voice stack is actually used, so it never breaks headless/test runs.
"""

from __future__ import annotations

from pipecat.frames.frames import (
    Frame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService

from ..config import Config
from ..memory.store import MemoryStore
from .claude_brain import ClaudeBrain


class ClaudeAgentSDKLLM(LLMService):
    def __init__(self, brain: ClaudeBrain, store: MemoryStore, cfg: Config, **kwargs):
        super().__init__(**kwargs)
        self._brain = brain
        self._store = store
        self._cfg = cfg

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if not isinstance(frame, LLMContextFrame):
            await self.push_frame(frame, direction)
            return

        user_text = _latest_user_text(frame)
        if not user_text:
            return

        self._store.log_turn("user", user_text)
        memories = [m.text for m in self._store.recall(user_text, limit=self._cfg.memory.recall_limit)]

        await self.push_frame(LLMFullResponseStartFrame())
        await self.start_processing_metrics()
        reply_parts: list[str] = []
        try:
            async for chunk in self._brain.ask(user_text, memories):
                reply_parts.append(chunk)
                await self.push_frame(LLMTextFrame(chunk))
        finally:
            await self.stop_processing_metrics()
            await self.push_frame(LLMFullResponseEndFrame())

        reply = "".join(reply_parts).strip()
        if reply:
            self._store.log_turn("assistant", reply)


def _latest_user_text(frame: LLMContextFrame) -> str:
    """Extract the most recent user message text from the pipeline context."""
    try:
        messages = frame.context.get_messages()
    except Exception:
        return ""
    for message in reversed(messages):
        if _role(message) == "user":
            return _content_text(message)
    return ""


def _role(message) -> str:
    if isinstance(message, dict):
        return message.get("role", "")
    return getattr(message, "role", "")


def _content_text(message) -> str:
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(getattr(block, "text", None), str):
                parts.append(block.text)
        return " ".join(parts).strip()
    return ""
