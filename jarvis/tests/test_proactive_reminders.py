"""Tests for reminder-driven proactivity and guard-bypass behaviour."""

from datetime import datetime

import pytest

from zemark.config import Config, ProactiveConfig
from zemark.memory.store import MemoryStore
from zemark.proactive.engine import ProactiveEngine
from zemark.proactive.triggers import (
    DailySummaryTrigger,
    PendingProjectTrigger,
    ProactiveContext,
    ReminderDueTrigger,
)
from zemark.reminders import ReminderStore


@pytest.fixture()
def stores(tmp_path):
    mem = MemoryStore(tmp_path / "m.sqlite3")
    rem = ReminderStore(tmp_path / "r.sqlite3")
    yield mem, rem
    mem.close()
    rem.close()


def _ctx(mem, rem, now):
    return ProactiveContext(
        now=now, store=mem, last_proactive_ts=0.0,
        last_interaction_ts=now.timestamp(), reminder_store=rem,
    )


def test_reminder_due_trigger_fires_and_consumes(stores):
    mem, rem = stores
    now = datetime.now().astimezone()
    rem.add("reunião com o time", now.timestamp() - 5)
    trig = ReminderDueTrigger()
    desc = trig.check(_ctx(mem, rem, now))
    assert desc is not None and "reunião com o time" in desc
    # consumed -> no repeat
    assert trig.check(_ctx(mem, rem, now)) is None
    assert trig.bypass_guards is True


def test_daily_summary_needs_pending(stores):
    mem, rem = stores
    evening = datetime(2026, 7, 23, 19, 0, 0).astimezone()
    trig = DailySummaryTrigger()
    assert trig.check(_ctx(mem, rem, evening)) is None  # nothing pending
    rem.add("enviar relatório", evening.timestamp() + 3600)
    assert trig.check(_ctx(mem, rem, evening)) is not None


def test_pending_project_once_per_day(stores):
    mem, rem = stores
    mem.remember("Está construindo o ZEMARK", kind="project", confidence=0.9)
    now = datetime.now().astimezone()
    trig = PendingProjectTrigger()
    assert trig.check(_ctx(mem, rem, now)) is not None
    assert trig.check(_ctx(mem, rem, now)) is None  # not twice the same day


@pytest.mark.asyncio
async def test_engine_fires_reminder_during_quiet_hours(stores):
    mem, rem = stores
    # quiet hours cover the whole day so a normal trigger would be blocked
    cfg = Config(proactive=ProactiveConfig(quiet_start_hour=0, quiet_end_hour=23, min_gap_seconds=99999))
    import time

    rem.add("tomar remédio", time.time() - 1)

    spoken = []

    async def draft(_p):
        return "Lembrete: tomar remédio."

    async def speak(t):
        spoken.append(t)

    eng = ProactiveEngine(cfg, mem, draft, speak, reminder_store=rem)
    await eng._tick()
    assert spoken and "remédio" in spoken[0]  # bypassed quiet-hours + min-gap
