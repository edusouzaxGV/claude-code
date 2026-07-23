"""The proactive loop: lets ZEMARK initiate, tastefully.

Every ``tick_seconds`` the engine evaluates its triggers. When one fires, it
asks the brain to draft a short spoken opener (persona "proactive" mode). The
brain may decline by replying ``SKIP`` — the whole point is to be helpful, not
naggy. Several guards enforce good manners:

    * **Quiet hours** — silent overnight.
    * **Min gap** — never two proactive nudges within ``min_gap_seconds``.
    * **Not while busy** — never interrupts an active conversation (the app
      exposes ``is_busy``).

The engine is transport-agnostic: it just calls an async ``speak(text)`` you
provide, so the same engine works for the desktop (Pipecat) and web (LiveKit)
front-ends.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime

from ..config import Config
from ..memory.store import MemoryStore
from ..persona import PROACTIVE_SKIP, build_system_prompt
from .triggers import ProactiveContext, Trigger, default_triggers

SpeakFn = Callable[[str], Awaitable[None]]
DraftFn = Callable[[str], Awaitable[str]]  # (proactive_system_prompt) -> spoken line
BusyFn = Callable[[], bool]


class ProactiveEngine:
    def __init__(
        self,
        cfg: Config,
        store: MemoryStore,
        draft: DraftFn,
        speak: SpeakFn,
        *,
        is_busy: BusyFn | None = None,
        triggers: list[Trigger] | None = None,
    ):
        self._cfg = cfg
        self._store = store
        self._draft = draft
        self._speak = speak
        self._is_busy = is_busy or (lambda: False)
        self._triggers = triggers or default_triggers(cfg.proactive.quiet_end_hour)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_proactive_ts = 0.0
        self._last_interaction_ts = time.time()

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        if not self._cfg.proactive.enabled:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="zemark-proactive")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    def note_interaction(self) -> None:
        """Call whenever the user interacts, so triggers can respect idleness."""
        self._last_interaction_ts = time.time()

    # -- loop -------------------------------------------------------------
    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._cfg.proactive.tick_seconds)
                break  # stop was set
            except asyncio.TimeoutError:
                pass  # normal tick
            try:
                await self._tick()
            except Exception:
                # never let a bad trigger kill the loop
                continue

    async def _tick(self) -> None:
        if self._is_busy() or self._in_quiet_hours() or self._too_soon():
            return

        ctx = ProactiveContext(
            now=datetime.now().astimezone(),
            store=self._store,
            last_proactive_ts=self._last_proactive_ts,
            last_interaction_ts=self._last_interaction_ts,
        )

        for trigger in self._triggers:
            description = trigger.check(ctx)
            if not description:
                continue
            line = await self._draft_line(description)
            if line and line.strip().upper() != PROACTIVE_SKIP:
                if self._is_busy():  # re-check: user may have started talking
                    return
                self._last_proactive_ts = time.time()
                await self._speak(line.strip())
            return  # one trigger per tick, fired or skipped

    async def _draft_line(self, trigger_description: str) -> str:
        memories = [m.text for m in self._store.recent(limit=self._cfg.memory.recall_limit)]
        system_prompt = build_system_prompt(
            self._cfg, memories=memories, proactive_trigger=trigger_description
        )
        return await self._draft(system_prompt)

    # -- guards -----------------------------------------------------------
    def _too_soon(self) -> bool:
        return (time.time() - self._last_proactive_ts) < self._cfg.proactive.min_gap_seconds

    def _in_quiet_hours(self) -> bool:
        hour = datetime.now().astimezone().hour
        start = self._cfg.proactive.quiet_start_hour
        end = self._cfg.proactive.quiet_end_hour
        if start == end:
            return False
        if start < end:
            return start <= hour < end
        # wraps midnight (e.g. 23 -> 8)
        return hour >= start or hour < end
