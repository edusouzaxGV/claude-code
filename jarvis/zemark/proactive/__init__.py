"""Proactivity: ZEMARK speaking first, tastefully."""

from .engine import ProactiveEngine
from .triggers import (
    DailyGreetingTrigger,
    DailySummaryTrigger,
    LooseThreadTrigger,
    PendingProjectTrigger,
    ProactiveContext,
    ReminderDueTrigger,
    Trigger,
    default_triggers,
)

__all__ = [
    "ProactiveEngine",
    "Trigger",
    "ProactiveContext",
    "DailyGreetingTrigger",
    "LooseThreadTrigger",
    "ReminderDueTrigger",
    "DailySummaryTrigger",
    "PendingProjectTrigger",
    "default_triggers",
]
