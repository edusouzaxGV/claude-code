"""Tests for auto-learning (reflection)."""

import pytest

from zemark.memory.reflection import ReflectionEngine, parse_facts
from zemark.memory.store import MemoryStore, Turn


def test_parse_facts_plain_array():
    raw = '[{"text": "Prefere café forte", "kind": "preference", "confidence": 0.9}]'
    facts = parse_facts(raw, min_confidence=0.55)
    assert len(facts) == 1
    assert facts[0].kind == "preference"


def test_parse_facts_strips_code_fence_and_prose():
    raw = 'Claro! Aqui vai:\n```json\n[{"text":"Mora em SP","confidence":0.8}]\n```'
    facts = parse_facts(raw, min_confidence=0.55)
    assert facts and facts[0].text == "Mora em SP"


def test_parse_facts_drops_low_confidence():
    raw = '[{"text":"talvez goste de jazz","confidence":0.2}]'
    assert parse_facts(raw, min_confidence=0.55) == []


def test_parse_facts_handles_garbage():
    assert parse_facts("não sei", min_confidence=0.5) == []
    assert parse_facts("[]", min_confidence=0.5) == []


@pytest.mark.asyncio
async def test_reflect_persists_facts(tmp_path):
    store = MemoryStore(tmp_path / "m.sqlite3")

    async def fake_complete(prompt: str) -> str:
        return '[{"text": "Prefere ser chamado de chefe", "kind": "preference", "confidence": 0.9}]'

    engine = ReflectionEngine(store, fake_complete, min_confidence=0.55)
    turns = [Turn(1, "user", "me chame de chefe", 0.0), Turn(2, "assistant", "certo", 1.0)]
    facts = await engine.reflect(turns)
    assert len(facts) == 1
    assert store.count() == 1
    store.close()


@pytest.mark.asyncio
async def test_reflect_noop_without_user_turn(tmp_path):
    store = MemoryStore(tmp_path / "m.sqlite3")

    async def fake_complete(prompt: str) -> str:  # pragma: no cover - shouldn't run
        raise AssertionError("should not be called")

    engine = ReflectionEngine(store, fake_complete)
    facts = await engine.reflect([Turn(1, "assistant", "olá", 0.0)])
    assert facts == []
    store.close()
