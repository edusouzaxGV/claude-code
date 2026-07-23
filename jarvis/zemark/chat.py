"""Text mode — talk to ZEMARK without any audio stack.

This is the fastest way to test the *brain*: memory, auto-learning, tools
(reminders/weather/etc.), and proactivity all run exactly as they do in the
voice app — you just type instead of speak. No microphone, no Pipecat, no
Kokoro. The only requirements are ``claude-agent-sdk`` and a subscription token
(``CLAUDE_CODE_OAUTH_TOKEN``).

Commands:
    /sair        end the session (runs a final auto-learn pass)
    /memoria     show what ZEMARK remembers
    /lembretes   show pending reminders
    /aprender    force an auto-learn pass now
    /ajuda       show this help
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from datetime import datetime

from .brain.claude_brain import ClaudeBrain
from .config import Config
from .memory.reflection import ReflectionEngine
from .memory.store import MemoryStore
from .proactive.engine import ProactiveEngine
from .reminders import ReminderStore
from .tools.builtin import build_tool_server

_PROMPT = "você> "


def _tuned_for_chat(cfg: Config) -> Config:
    """Make proactivity snappy & always-on so it's observable while testing."""
    proactive = replace(
        cfg.proactive,
        tick_seconds=min(cfg.proactive.tick_seconds, 5.0),
        min_gap_seconds=min(cfg.proactive.min_gap_seconds, 20.0),
        quiet_start_hour=0,
        quiet_end_hour=0,  # start==end disables quiet hours
    )
    return replace(cfg, proactive=proactive)


class ChatSession:
    def __init__(self, cfg: Config, store: MemoryStore, reminders: ReminderStore):
        self._cfg = _tuned_for_chat(cfg)
        self._store = store
        self._reminders = reminders
        self._brain: ClaudeBrain | None = None
        self._proactive: ProactiveEngine | None = None
        self._reflection: ReflectionEngine | None = None
        self._busy = False
        self._session_start = datetime.now().timestamp()

    async def _speak(self, text: str) -> None:
        # \r clears the current input prompt line before ZEMARK interjects
        sys.stdout.write("\r\033[K")
        print(f"\033[36mZEMARK (proativo):\033[0m {text}\n")
        sys.stdout.write(_PROMPT)
        sys.stdout.flush()
        self._store.log_turn("assistant", text)

    async def start(self) -> None:
        tool_server, allowed = build_tool_server(self._store, self._reminders)
        self._brain = ClaudeBrain(self._cfg, tool_server=tool_server, allowed_tools=allowed)
        await self._brain.start()

        if self._cfg.memory.auto_learn:
            self._reflection = ReflectionEngine(
                self._store, self._brain.complete,
                user_name=self._cfg.user_name, assistant_name=self._cfg.assistant_name,
                min_confidence=self._cfg.memory.min_confidence,
            )

        self._proactive = ProactiveEngine(
            self._cfg, self._store,
            draft=self._brain.complete, speak=self._speak,
            is_busy=lambda: self._busy, reminder_store=self._reminders,
        )
        self._proactive.start()

    async def stop(self) -> None:
        if self._proactive:
            await self._proactive.stop()
        if self._reflection:
            await self._reflect()
        if self._brain:
            await self._brain.aclose()

    async def _reflect(self) -> None:
        if not self._reflection:
            return
        turns = self._store.turns_since(self._session_start)
        facts = await self._reflection.reflect(turns)
        if facts:
            print(f"\033[90m· aprendi {len(facts)} coisa(s) sobre você nesta conversa.\033[0m")

    async def handle(self, text: str) -> bool:
        """Process one line. Returns False to end the session."""
        text = text.strip()
        if not text:
            return True
        if text in {"/sair", "/quit", "/exit"}:
            return False
        if text == "/ajuda":
            print(__doc__)
            return True
        if text == "/memoria":
            mems = self._store.all()
            print("\n".join(f"  [{m.kind}·{m.confidence:.2f}] {m.text}" for m in mems) or "  (vazia)")
            return True
        if text == "/lembretes":
            up = self._reminders.upcoming(limit=20)
            for r in up:
                q = datetime.fromtimestamp(r.due_ts).astimezone().strftime("%d/%m %H:%M")
                print(f"  [{q}] {r.text}")
            if not up:
                print("  (nenhum)")
            return True
        if text == "/aprender":
            await self._reflect()
            return True

        # normal turn
        self._busy = True
        try:
            self._store.log_turn("user", text)
            memories = [m.text for m in self._store.recall(text, limit=self._cfg.memory.recall_limit)]
            sys.stdout.write("\033[32mZEMARK:\033[0m ")
            sys.stdout.flush()
            parts: list[str] = []
            async for chunk in self._brain.ask(text, memories):
                parts.append(chunk)
                sys.stdout.write(chunk)
                sys.stdout.flush()
            print()
            reply = "".join(parts).strip()
            if reply:
                self._store.log_turn("assistant", reply)
        finally:
            self._busy = False
        return True


async def run_chat(cfg: Config, store: MemoryStore, reminders: ReminderStore) -> None:
    session = ChatSession(cfg, store, reminders)
    try:
        await session.start()
    except Exception as exc:
        print(f"Não consegui iniciar o cérebro: {exc}")
        print("Verifique: `pip install claude-agent-sdk` e `claude setup-token` "
              "(veja `python run.py doctor`).")
        return

    print(f"💬 {cfg.assistant_name} em modo texto. Converse à vontade. /ajuda para comandos, /sair para sair.\n")
    loop = asyncio.get_running_loop()
    try:
        while True:
            try:
                line = await loop.run_in_executor(None, input, _PROMPT)
            except (EOFError, KeyboardInterrupt):
                break
            keep_going = await session.handle(line)
            if not keep_going:
                break
    finally:
        print("\n· encerrando…")
        await session.stop()
        print("até logo.")
