"""Tests for the phrase-based wake matcher (the zero-setup default)."""

from zemark.wake.phrase import PhraseMatcher, _normalize

ALIASES = ("zemark", "ze mark", "zé mark", "zi mark", "zemarki", "zemarck", "z mark")


def matcher() -> PhraseMatcher:
    return PhraseMatcher(word="zemark", aliases=ALIASES)


def test_exact_match():
    m = matcher()
    assert m.matches("zemark que horas são")
    assert m.matches("ZEMARK, tudo bem?")


def test_accent_and_case_insensitive():
    m = matcher()
    assert m.matches("Zé Mark, liga a luz")
    assert _normalize("Zé Mark") == "ze mark"


def test_alias_and_stt_drift():
    m = matcher()
    assert m.matches("zi mark toca uma música")
    assert m.matches("zemarck me ajuda")  # common STT mangling


def test_fuzzy_close_variant():
    m = matcher()
    # a near-miss the STT might produce should still fuzzily match
    assert m.matches("zemarki abre o navegador")


def test_negative_does_not_trigger():
    m = matcher()
    assert not m.matches("que horas são")
    assert not m.matches("preciso marcar uma reunião")  # 'marcar' must not trip it
    assert not m.matches("")


def test_strip_wake_returns_command():
    m = matcher()
    assert m.strip_wake("zemark que horas são") == "que horas são"
    assert m.strip_wake("Zé Mark liga a luz") == "liga a luz"


def test_strip_wake_bare_word():
    m = matcher()
    assert m.strip_wake("zemark") == ""
