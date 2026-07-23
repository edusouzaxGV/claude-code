"""Proactive triggers — the reasons ZEMARK might speak first.

A trigger inspects the current context and, if something is worth surfacing,
returns a short natural-language description of *what it noticed*. The proactive
engine then asks the brain to turn that into a spoken opener (or to stay quiet).

Triggers are deliberately small and pure so they are easy to unit-test and easy
to extend — add a class, implement ``check``, register it. Nothing here does
I/O beyond reading the memory store.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..memory.store import MemoryStore


@dataclass
class ProactiveContext:
    now: datetime
    store: MemoryStore
    last_proactive_ts: float  # epoch seconds of the last proactive utterance
    last_interaction_ts: float  # epoch seconds of the last user interaction
    reminder_store: object | None = None  # ReminderStore, optional


class Trigger(Protocol):
    name: str

    def check(self, ctx: ProactiveContext) -> str | None: ...


# Phrases that suggest ZEMARK promised to follow up on something.
_FOLLOWUP_HINTS = (
    "te aviso",
    "te lembro",
    "depois eu",
    "mais tarde",
    "em seguida",
    "daqui a pouco",
    "assim que",
    "quando terminar",
    "vou verificar",
    "deixa comigo",
)


class DailyGreetingTrigger:
    """Greet once per day the first time the user is around in the morning."""

    name = "daily_greeting"

    def __init__(self, start_hour: int = 8, end_hour: int = 11):
        self.start_hour = start_hour
        self.end_hour = end_hour

    def check(self, ctx: ProactiveContext) -> str | None:
        if not (self.start_hour <= ctx.now.hour < self.end_hour):
            return None
        today = ctx.now.strftime("%Y-%m-%d")
        if ctx.store.get_meta("last_greeting_day") == today:
            return None
        ctx.store.set_meta("last_greeting_day", today)
        return (
            "É de manhã e você ainda não conversou comigo hoje. "
            "Uma saudação breve e uma oferta de ajuda para começar o dia."
        )


class LooseThreadTrigger:
    """Notice when ZEMARK earlier implied it would follow up on something."""

    name = "loose_thread"

    def __init__(self, min_age_seconds: float = 180.0, max_age_seconds: float = 3600.0):
        self.min_age = min_age_seconds
        self.max_age = max_age_seconds

    def check(self, ctx: ProactiveContext) -> str | None:
        # only if the user has gone a little quiet (not mid-conversation)
        idle = time.time() - ctx.last_interaction_ts
        if idle < self.min_age or idle > self.max_age:
            return None
        marker = ctx.store.get_meta("loose_thread_handled_at")
        for turn in reversed(ctx.store.recent_turns(limit=8)):
            if turn.role != "assistant":
                continue
            low = turn.text.lower()
            if any(hint in low for hint in _FOLLOWUP_HINTS):
                if marker == str(int(turn.created_at)):
                    return None  # already acted on this one
                ctx.store.set_meta("loose_thread_handled_at", str(int(turn.created_at)))
                return (
                    "Mais cedo você comentou algo em que eu disse que daria "
                    f"sequência: \"{turn.text.strip()}\". Retome isso de forma breve, "
                    "perguntando se quer que eu siga com aquilo agora."
                )
        return None


class ReminderDueTrigger:
    """Speak reminders the moment they come due. Never skipped.

    ``bypass_guards`` tells the engine this is a *solicited* utterance, so it
    ignores quiet-hours and the anti-nag min-gap — an explicit reminder must
    fire on time, even at 2am or right after another proactive line.
    """

    name = "reminder_due"
    bypass_guards = True

    def check(self, ctx: ProactiveContext) -> str | None:
        if ctx.reminder_store is None:
            return None
        due = ctx.reminder_store.due(ctx.now.timestamp())
        if not due:
            return None
        reminder = due[0]
        # consume it now so it doesn't repeat, even if delivery is terse
        ctx.reminder_store.mark_fired(reminder.id)
        return (
            f"Lembrete que o usuário pediu: \"{reminder.text}\". "
            "Avise agora, de forma direta e curta. Este é um lembrete explícito — NÃO pule."
        )


class DailySummaryTrigger:
    """Once a day in the evening, offer a brief rundown of what's pending."""

    name = "daily_summary"

    def __init__(self, start_hour: int = 18, end_hour: int = 22):
        self.start_hour = start_hour
        self.end_hour = end_hour

    def check(self, ctx: ProactiveContext) -> str | None:
        if not (self.start_hour <= ctx.now.hour < self.end_hour):
            return None
        today = ctx.now.strftime("%Y-%m-%d")
        if ctx.store.get_meta("last_summary_day") == today:
            return None

        pending = []
        if ctx.reminder_store is not None:
            pending = [r.text for r in ctx.reminder_store.upcoming(limit=5)]
        # only bother if there's actually something to summarise
        if not pending:
            return None
        ctx.store.set_meta("last_summary_day", today)
        itens = "; ".join(pending)
        return (
            "Fim de tarde. Faça um resumo curtíssimo dos lembretes/pendências e "
            f"ofereça ajuda para fechar o dia. Pendências: {itens}."
        )


class PendingProjectTrigger:
    """Occasionally nudge about an ongoing project ZEMARK has noted, at most once/day."""

    name = "pending_project"

    def check(self, ctx: ProactiveContext) -> str | None:
        today = ctx.now.strftime("%Y-%m-%d")
        if ctx.store.get_meta("last_project_nudge_day") == today:
            return None
        projects = [m for m in ctx.store.recent(limit=20) if m.kind == "project"]
        if not projects:
            return None
        ctx.store.set_meta("last_project_nudge_day", today)
        proj = projects[0]
        return (
            f"Você tem um projeto em andamento que anotei: \"{proj.text}\". "
            "Pergunte, de forma leve e breve, se quer avançar nele agora. "
            "Se não parecer o momento, responda SKIP."
        )


def default_triggers(quiet_end_hour: int = 8, reminder_store=None) -> list[Trigger]:
    triggers: list[Trigger] = []
    if reminder_store is not None:
        triggers.append(ReminderDueTrigger())  # highest priority
    triggers.append(DailyGreetingTrigger(start_hour=max(quiet_end_hour, 7), end_hour=11))
    triggers.append(LooseThreadTrigger())
    if reminder_store is not None:
        triggers.append(DailySummaryTrigger())
    triggers.append(PendingProjectTrigger())
    return triggers
