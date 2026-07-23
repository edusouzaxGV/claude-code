"""Tests for the persistent memory store."""

import pytest

from zemark.memory.store import MemoryStore


@pytest.fixture()
def store(tmp_path):
    s = MemoryStore(tmp_path / "mem.sqlite3")
    yield s
    s.close()


def test_remember_and_recall(store):
    store.remember("Prefere respostas curtas", kind="preference")
    store.remember("Trabalha com engenharia de software", kind="fact")
    hits = store.recall("respostas")
    assert any("curtas" in m.text for m in hits)


def test_recall_no_match_returns_empty(store):
    store.remember("Usa um Mac com Apple Silicon")
    # a genuine non-match returns nothing (we don't inject irrelevant memories)
    assert store.recall("xyzzy-inexistente") == []


def test_dedupe_reinforces_instead_of_duplicating(store):
    id1 = store.remember("Prefere respostas curtas e diretas")
    id2 = store.remember("Prefere respostas curtas e diretas")
    assert id1 == id2
    assert store.count() == 1


def test_forget(store):
    mid = store.remember("Segredo temporário")
    assert store.forget(mid)
    assert store.count() == 0


def test_forget_matching(store):
    store.remember("Gosta de café pela manhã")
    store.remember("Gosta de café forte")
    removed = store.forget_matching("café")
    assert removed >= 1


def test_turns_log_and_recent(store):
    store.log_turn("user", "oi")
    store.log_turn("assistant", "olá, chefe")
    turns = store.recent_turns(limit=10)
    assert [t.role for t in turns] == ["user", "assistant"]


def test_meta_roundtrip(store):
    store.set_meta("last_greeting_day", "2026-07-23")
    assert store.get_meta("last_greeting_day") == "2026-07-23"
    assert store.get_meta("missing", "default") == "default"


def test_fts_special_chars_do_not_crash(store):
    store.remember("Projeto (Alpha) * importante")
    # a query with FTS-special characters must not raise
    assert isinstance(store.recall('(alpha) * "x"'), list)
