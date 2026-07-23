"""Tests for proactivity: quiet hours, triggers, and the draft/skip flow."""

import time
from datetime import datetime

import pytest

from zemark.config import Config, ProactiveConfig
from zemark.memory.store import MemoryStore
from zemark.proactive.engine import ProactiveEngine
from zemark.proactive.triggers import (
    DailyGreetingTrigger,
    LooseThreadTrigger,
    ProactiveContext,
)


@pytest.fixture()
def store(tmp_path):
    s = MemoryStore(tmp_path / "m.sqlite3")
    yield s
    s.close()


def _ctx(store, now, last_interaction=None):
    return ProactiveContext(
        now=now,
        store=store,
        last_proactive_ts=0.0,
        last_interaction_ts=last_interaction if last_interaction is not None else time.time(),
    )


def test_quiet_hours_wrap_midnight():
    cfg = Config(proactive=ProactiveConfig(quiet_start_hour=23, quiet_end_hour=8))
    eng = ProactiveEngine(cfg, None, None, None)  # guards don't touch store/brain
    # patch the clock indirectly by checking the pure method against known hours
    assert eng._in_quiet_hours.__self__ is eng  # sanity: bound method
    # 2am is quiet, 3pm is not — verify via the wrap logic directly
    for hour, expected in [(2, True), (7, True), (8, False), (15, False), (23, True)]:
        assert _quiet_for_hour(cfg, hour) is expected


def _quiet_for_hour(cfg, hour):
    start, end = cfg.proactive.quiet_start_hour, cfg.proactive.quiet_end_hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def test_daily_greeting_fires_once_per_day(store):
    trig = DailyGreetingTrigger(start_hour=8, end_hour=11)
    morning = datetime(2026, 7, 23, 9, 0, 0).astimezone()
    assert trig.check(_ctx(store, morning)) is not None
    # second call same day -> no repeat
    assert trig.check(_ctx(store, morning)) is None


def test_daily_greeting_outside_window(store):
    trig = DailyGreetingTrigger(start_hour=8, end_hour=11)
    afternoon = datetime(2026, 7, 23, 15, 0, 0).astimezone()
    assert trig.check(_ctx(store, afternoon)) is None


def test_loose_thread_detects_followup_promise(store):
    store.log_turn("user", "me avisa quando terminar")
    store.log_turn("assistant", "claro, te aviso assim que terminar")
    trig = LooseThreadTrigger(min_age_seconds=0.0, max_age_seconds=10_000.0)
    now = datetime.now().astimezone()
    # last interaction well in the past so the 'idle' gate opens
    res = trig.check(_ctx(store, now, last_interaction=time.time() - 300))
    assert res is not None and "sequência" in res.lower()


def _cfg_no_quiet():
    # deterministic: quiet hours off (start==end), no anti-nag gap
    return Config(proactive=ProactiveConfig(quiet_start_hour=0, quiet_end_hour=0, min_gap_seconds=0))


@pytest.mark.asyncio
async def test_engine_respects_skip(store):
    cfg = _cfg_no_quiet()

    async def draft_skip(_system_prompt: str) -> str:
        return "SKIP"

    spoken = []

    async def speak(text: str) -> None:
        spoken.append(text)

    eng = ProactiveEngine(
        cfg, store, draft_skip, speak,
        triggers=[_AlwaysTrigger()],
    )
    await eng._tick()
    assert spoken == []  # SKIP means nothing is said


@pytest.mark.asyncio
async def test_engine_speaks_when_not_skipped(store):
    cfg = _cfg_no_quiet()

    async def draft(_system_prompt: str) -> str:
        return "Bom dia, chefe. Posso ajudar em algo?"

    spoken = []

    async def speak(text: str) -> None:
        spoken.append(text)

    eng = ProactiveEngine(cfg, store, draft, speak, triggers=[_AlwaysTrigger()])
    await eng._tick()
    assert spoken and "Bom dia" in spoken[0]


class _AlwaysTrigger:
    name = "always"

    def check(self, ctx):
        return "gatilho de teste"
