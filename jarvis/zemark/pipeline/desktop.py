"""Desktop voice agent assembly (Pipecat 1.6).

This is the one module that is sensitive to Pipecat's version. It follows the
1.6 API: ``PipelineWorker`` / ``WorkerRunner``, provider-neutral ``LLMContext``,
and VAD/turn-detection configured on the *user aggregator* (not the transport).
Interruptions/barge-in are automatic once a VAD analyzer is present.

Pin ``pipecat-ai==1.6.*`` (see requirements.txt). If you upgrade and the import
names shift, this file is the only place you should need to touch.
"""

from __future__ import annotations

import asyncio

from ..brain.claude_brain import ClaudeBrain
from ..brain.pipecat_llm import ClaudeAgentSDKLLM
from ..config import Config
from ..memory.reflection import ReflectionEngine
from ..memory.store import MemoryStore
from ..proactive.engine import ProactiveEngine
from ..stt.factory import build_stt
from ..tts.factory import build_tts
from ..tools.builtin import build_tool_server
from ..wake.phrase import PhraseMatcher
from .wake_gate import WakeGate


class DesktopAgent:
    def __init__(self, cfg: Config, store: MemoryStore):
        self._cfg = cfg
        self._store = store
        self._brain: ClaudeBrain | None = None
        self._worker = None
        self._runner = None
        self._wake_gate: WakeGate | None = None
        self._proactive: ProactiveEngine | None = None
        self._reflection: ReflectionEngine | None = None
        self._reflect_task = None

    async def build(self) -> None:
        from pipecat.audio.vad.silero import SileroVADAnalyzer
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.worker import PipelineParams, PipelineWorker
        from pipecat.processors.aggregators.llm_context import LLMContext
        from pipecat.processors.aggregators.llm_response_universal import (
            LLMContextAggregatorPair,
            LLMUserAggregatorParams,
        )
        from pipecat.transports.local.audio import (
            LocalAudioTransport,
            LocalAudioTransportParams,
        )
        from pipecat.workers.runner import WorkerRunner

        # brain + tools
        tool_server, allowed = build_tool_server(self._store)
        self._brain = ClaudeBrain(self._cfg, tool_server=tool_server, allowed_tools=allowed)
        await self._brain.start()

        # audio + services
        transport = LocalAudioTransport(
            LocalAudioTransportParams(audio_in_enabled=True, audio_out_enabled=True)
        )
        stt = build_stt(self._cfg)
        tts = build_tts(self._cfg)
        llm = ClaudeAgentSDKLLM(self._brain, self._store, self._cfg)

        # wake gate (phrase-based, integrated with the always-on STT)
        matcher = PhraseMatcher(word=self._cfg.wake.word, aliases=self._cfg.wake.aliases)
        self._wake_gate = WakeGate(
            matcher, idle_timeout=self._cfg.audio.conversation_idle_timeout
        )

        # context + VAD/turn-taking on the user aggregator
        context = LLMContext()
        user_agg, assistant_agg = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
        )

        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                self._wake_gate,
                user_agg,
                llm,
                tts,
                transport.output(),
                assistant_agg,
            ]
        )
        self._worker = PipelineWorker(pipeline, params=PipelineParams(enable_metrics=True))
        self._runner = WorkerRunner()

        # auto-learning (reflection after each conversation)
        if self._cfg.memory.auto_learn:
            self._reflection = ReflectionEngine(
                self._store,
                self._brain.complete,
                user_name=self._cfg.user_name,
                assistant_name=self._cfg.assistant_name,
                min_confidence=self._cfg.memory.min_confidence,
            )

        # proactivity
        self._proactive = ProactiveEngine(
            self._cfg,
            self._store,
            draft=self._brain.complete,
            speak=self._speak,
            is_busy=lambda: bool(self._wake_gate and self._wake_gate.conversation_open),
        )

    async def _speak(self, text: str) -> None:
        """Push a proactive utterance straight to TTS."""
        from pipecat.frames.frames import TTSSpeakFrame

        if self._worker is not None:
            self._store.log_turn("assistant", text)
            await self._worker.queue_frames([TTSSpeakFrame(text)])
            if self._wake_gate is not None:
                # keep the window open so the user can reply without the wake word
                self._wake_gate.touch()

    async def _reflect_watcher(self) -> None:
        """Run the auto-learning pass at the close of each conversation window."""
        import time as _time

        was_open = False
        opened_at = _time.time()
        while True:
            await asyncio.sleep(2.0)
            if self._wake_gate is None or self._reflection is None:
                continue
            now_open = self._wake_gate.conversation_open
            if now_open and not was_open:
                opened_at = _time.time()
            elif was_open and not now_open:
                turns = self._store.turns_since(opened_at)
                try:
                    await self._reflection.reflect(turns)
                except Exception:
                    pass  # never let learning crash the agent
            was_open = now_open

    async def run(self) -> None:
        if self._worker is None:
            await self.build()
        assert self._proactive and self._runner and self._worker
        self._proactive.start()
        if self._reflection is not None:
            self._reflect_task = asyncio.create_task(self._reflect_watcher())
        try:
            await self._runner.add_workers(self._worker)
            await self._runner.run()
        finally:
            await self._proactive.stop()
            if self._reflect_task is not None:
                self._reflect_task.cancel()
            if self._brain is not None:
                await self._brain.aclose()


async def run_desktop(cfg: Config, store: MemoryStore) -> None:
    agent = DesktopAgent(cfg, store)
    await agent.run()


def main() -> None:  # console entry
    from ..config import load_config

    cfg = load_config()
    store = MemoryStore(cfg.memory.db_path)
    try:
        asyncio.run(run_desktop(cfg, store))
    finally:
        store.close()
