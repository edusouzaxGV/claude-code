#!/usr/bin/env python3
"""ZEMARK launcher.

Usage:
    python run.py                 # start the desktop voice agent (wake word: ZEMARK)
    python run.py doctor          # check environment / auth without starting audio
    python run.py memory          # print what ZEMARK remembers
    python run.py livekit ...     # run the web/phone agent (passes args to LiveKit CLI)

The launcher makes sure subscription auth is actually used: if
ZEMARK_FORCE_SUBSCRIPTION_AUTH is on (default), it removes ANTHROPIC_API_KEY
from the environment before anything runs, because that key silently outranks
the Claude subscription OAuth token and would bill you per request.
"""

from __future__ import annotations

import asyncio
import os
import sys


def _scrub_api_key(cfg) -> None:
    if cfg.brain.force_subscription_auth and os.environ.pop("ANTHROPIC_API_KEY", None):
        print("• Removi ANTHROPIC_API_KEY do ambiente para usar a assinatura Claude.")


def cmd_doctor() -> int:
    from zemark.config import load_config

    cfg = load_config()
    _scrub_api_key(cfg)
    print(f"ZEMARK doctor — assistente '{cfg.assistant_name}', usuário '{cfg.user_name}'")
    ok = True

    if os.getenv("CLAUDE_CODE_OAUTH_TOKEN"):
        print("✓ CLAUDE_CODE_OAUTH_TOKEN presente (auth por assinatura).")
    else:
        ok = False
        print("✗ CLAUDE_CODE_OAUTH_TOKEN ausente. Rode:  claude setup-token")
        print("   (precisa do CLI: npm install -g @anthropic-ai/claude-code)")

    print(f"• Cérebro: modelo '{cfg.brain.model}', permissão '{cfg.brain.permission_mode}'")
    print(f"• STT: {cfg.stt.provider}" + (
        "  (GROQ_API_KEY definido)" if cfg.groq_api_key else "  (sem GROQ_API_KEY — use whisper local)"
    ))
    print(f"• TTS: {cfg.tts.provider}, voz '{cfg.tts.voice}' ({cfg.tts.language})")
    print(f"• Wake: backend '{cfg.wake.backend}', palavra '{cfg.wake.word}'")
    print(f"• Proativo: {'on' if cfg.proactive.enabled else 'off'}  "
          f"| Auto-aprendizado: {'on' if cfg.memory.auto_learn else 'off'}")

    if cfg.stt.provider == "groq" and not cfg.groq_api_key:
        ok = False
        print("✗ STT=groq mas GROQ_API_KEY não definido.")

    print("\nDiagnóstico:", "tudo pronto ✅" if ok else "há pendências acima ⚠️")
    return 0 if ok else 1


def cmd_memory() -> int:
    from zemark.config import load_config
    from zemark.memory.store import MemoryStore

    cfg = load_config()
    store = MemoryStore(cfg.memory.db_path)
    mems = store.all()
    if not mems:
        print("(memória vazia — ZEMARK ainda vai te conhecer)")
    else:
        print(f"{len(mems)} memória(s):")
        for m in mems:
            print(f"  [{m.kind} · {m.confidence:.2f}] {m.text}")
    store.close()
    return 0


def cmd_desktop() -> int:
    from zemark.config import load_config
    from zemark.memory.store import MemoryStore
    from zemark.pipeline.desktop import run_desktop

    cfg = load_config()
    _scrub_api_key(cfg)
    if not os.getenv("CLAUDE_CODE_OAUTH_TOKEN") and cfg.brain.force_subscription_auth:
        print("⚠️  CLAUDE_CODE_OAUTH_TOKEN não definido — rode 'python run.py doctor'. Tentando mesmo assim…")

    store = MemoryStore(cfg.memory.db_path)
    print(f"🎙️  {cfg.assistant_name} online. Diga \"{cfg.wake.word}\" para falar. (Ctrl+C encerra)")
    try:
        asyncio.run(run_desktop(cfg, store))
    except KeyboardInterrupt:
        print("\nAté logo.")
    finally:
        store.close()
    return 0


def cmd_livekit(argv: list[str]) -> int:
    from zemark.config import load_config

    cfg = load_config()
    _scrub_api_key(cfg)
    # hand remaining args to the LiveKit CLI (console/dev/start)
    sys.argv = ["zemark-livekit", *argv]
    from zemark.livekit_agent import main as livekit_main

    livekit_main()
    return 0


def main() -> int:
    args = sys.argv[1:]
    cmd = args[0] if args else "run"

    if cmd in {"run", "desktop"}:
        return cmd_desktop()
    if cmd == "doctor":
        return cmd_doctor()
    if cmd == "memory":
        return cmd_memory()
    if cmd == "livekit":
        return cmd_livekit(args[1:])

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
