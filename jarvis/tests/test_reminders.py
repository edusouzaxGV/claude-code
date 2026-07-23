"""Tests for the reminders store and the Portuguese time parser."""

from datetime import datetime, timedelta

import pytest

from zemark.reminders import ReminderStore
from zemark.timeparse import parse_when


# -- time parser ----------------------------------------------------------
def _now():
    return datetime(2026, 7, 23, 10, 0, 0).astimezone()


def test_relative_minutes():
    now = _now()
    ts = parse_when("em 10 minutos", now)
    assert ts == (now + timedelta(minutes=10)).timestamp()


def test_relative_hours_and_daqui():
    now = _now()
    assert parse_when("daqui a 2 horas", now) == (now + timedelta(hours=2)).timestamp()


def test_relative_h_m_combo():
    now = _now()
    assert parse_when("em 1h30", now) == (now + timedelta(hours=1, minutes=30)).timestamp()


def test_absolute_future_today():
    now = _now()  # 10:00
    ts = parse_when("às 15h", now)
    assert datetime.fromtimestamp(ts).astimezone().hour == 15


def test_absolute_past_rolls_to_tomorrow():
    now = _now()  # 10:00
    ts = parse_when("às 9h", now)  # already past today
    dt = datetime.fromtimestamp(ts).astimezone()
    assert dt.day == now.day + 1 and dt.hour == 9


def test_amanha():
    now = _now()
    ts = parse_when("amanhã às 9h", now)
    dt = datetime.fromtimestamp(ts).astimezone()
    assert dt.day == now.day + 1 and dt.hour == 9


def test_hora_minuto_colon():
    now = _now()
    ts = parse_when("as 15:30", now)
    dt = datetime.fromtimestamp(ts).astimezone()
    assert dt.hour == 15 and dt.minute == 30


def test_no_time_returns_none():
    assert parse_when("faça isso por favor", _now()) is None


# -- store ----------------------------------------------------------------
@pytest.fixture()
def store(tmp_path):
    s = ReminderStore(tmp_path / "r.sqlite3")
    yield s
    s.close()


def test_add_and_due(store):
    now = 1000.0
    store.add("reunião", now - 5)     # already due
    store.add("almoço", now + 3600)   # future
    due = store.due(now)
    assert len(due) == 1 and due[0].text == "reunião"


def test_mark_fired_prevents_repeat(store):
    now = 1000.0
    rid = store.add("beber água", now - 1)
    store.mark_fired(rid)
    assert store.due(now) == []


def test_upcoming_ordered(store):
    store.add("b", 2000)
    store.add("a", 1500)
    up = store.upcoming()
    assert [r.text for r in up] == ["a", "b"]


def test_cancel_matching(store):
    store.add("ligar para o médico", 5000)
    store.add("ligar para a mãe", 5000)
    assert store.cancel_matching("ligar") == 2
    assert store.upcoming() == []
