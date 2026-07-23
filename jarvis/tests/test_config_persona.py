"""Tests for config loading and persona/system-prompt construction."""

import importlib

from zemark.persona import PROACTIVE_SKIP, build_system_prompt


def _fresh_config(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import zemark.config as config_mod

    importlib.reload(config_mod)
    return config_mod.load_config()


def test_defaults(monkeypatch):
    cfg = _fresh_config(monkeypatch)
    assert cfg.assistant_name == "ZEMARK"
    assert cfg.stt.provider == "groq"
    assert cfg.tts.language == "pt-br"
    assert cfg.wake.word == "zemark"
    assert cfg.proactive.enabled is True


def test_env_override(monkeypatch):
    cfg = _fresh_config(
        monkeypatch,
        ZEMARK_ASSISTANT_NAME="JARVIS",
        ZEMARK_STT_PROVIDER="whisper",
        ZEMARK_MAX_REPLY_SENTENCES="1",
    )
    assert cfg.assistant_name == "JARVIS"
    assert cfg.stt.provider == "whisper"
    assert cfg.brain.max_reply_sentences == 1


def test_wake_aliases_parsed(monkeypatch):
    cfg = _fresh_config(monkeypatch, ZEMARK_WAKE_ALIASES="zemark, ze mark ,zi mark")
    assert "ze mark" in cfg.wake.aliases
    assert "zi mark" in cfg.wake.aliases


def test_system_prompt_includes_identity_and_memory(monkeypatch):
    cfg = _fresh_config(monkeypatch)
    prompt = build_system_prompt(cfg, memories=["Prefere respostas curtas"])
    assert "ZEMARK" in prompt
    assert "Prefere respostas curtas" in prompt
    assert "conversa ao vivo" in prompt.lower()


def test_system_prompt_proactive_mode(monkeypatch):
    cfg = _fresh_config(monkeypatch)
    prompt = build_system_prompt(cfg, memories=None, proactive_trigger="reunião em 15 min")
    assert "reunião em 15 min" in prompt
    assert PROACTIVE_SKIP in prompt  # tells the model how to decline
    assert "iniciativa própria" in prompt.lower()


def test_system_prompt_no_memory_note(monkeypatch):
    cfg = _fresh_config(monkeypatch)
    prompt = build_system_prompt(cfg, memories=None)
    assert "começando a conhec" in prompt.lower() or "memória de longo prazo" not in prompt
