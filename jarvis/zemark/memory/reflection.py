"""Auto-learning: distil durable knowledge from a conversation.

After a conversation ends, ZEMARK re-reads the recent turns and asks its own
brain to extract a small set of *durable* facts worth remembering about the
user (preferences, recurring people/places, ongoing projects, standing
instructions). Ephemeral chatter is ignored. Extracted facts are de-duplicated
and reinforced by :class:`~zemark.memory.store.MemoryStore`, so the assistant
gets to know you a little better after every exchange.

This module is intentionally decoupled from the brain implementation: it takes
an async ``complete(prompt) -> str`` callable, so it works with the Claude
Agent SDK brain, a raw API client, or a stub in tests.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .store import MemoryStore, Turn

CompleteFn = Callable[[str], Awaitable[str]]

_EXTRACTION_PROMPT = """Você é o módulo de memória de um assistente pessoal. Leia a conversa abaixo e extraia APENAS fatos duráveis que valham a pena lembrar sobre o usuário no longo prazo: preferências, pessoas/lugares recorrentes, projetos em andamento, rotinas, instruções permanentes ("sempre faça X"), dados estáveis (fuso, ferramentas que usa).

NÃO extraia: perguntas triviais, conversa passageira, coisas de uma vez só, ou nada que já seja óbvio.

Responda SOMENTE com um array JSON (sem texto ao redor, sem markdown). Cada item:
  {{"text": "<fato em uma frase, em 3a pessoa, ex: 'Prefere respostas curtas'>",
    "kind": "preference|person|project|routine|instruction|fact",
    "confidence": <0.0 a 1.0>}}

Se não houver nada digno de memória, responda com: []

Conversa:
{conversation}
"""


@dataclass
class LearnedFact:
    text: str
    kind: str
    confidence: float


def _format_turns(turns: list[Turn], user_name: str, assistant_name: str) -> str:
    lines = []
    for t in turns:
        who = user_name if t.role == "user" else assistant_name
        lines.append(f"{who}: {t.text}")
    return "\n".join(lines)


def _extract_json_array(raw: str) -> list[dict]:
    """Best-effort parse of a JSON array from a possibly-noisy model reply."""
    raw = raw.strip()
    # strip ``` fences if the model added them despite instructions
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    # find the outermost [...]
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    candidate = raw[start : end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def parse_facts(raw: str, *, min_confidence: float) -> list[LearnedFact]:
    facts: list[LearnedFact] = []
    for item in _extract_json_array(raw):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        try:
            confidence = float(item.get("confidence", 0.6))
        except (TypeError, ValueError):
            confidence = 0.6
        if confidence < min_confidence:
            continue
        kind = str(item.get("kind", "fact")).strip() or "fact"
        facts.append(LearnedFact(text=text, kind=kind, confidence=confidence))
    return facts


class ReflectionEngine:
    def __init__(
        self,
        store: MemoryStore,
        complete: CompleteFn,
        *,
        user_name: str = "usuário",
        assistant_name: str = "ZEMARK",
        min_confidence: float = 0.55,
    ):
        self._store = store
        self._complete = complete
        self._user_name = user_name
        self._assistant_name = assistant_name
        self._min_confidence = min_confidence

    async def reflect(self, turns: list[Turn]) -> list[LearnedFact]:
        """Extract and persist durable facts from the given turns."""
        # need at least one user utterance to be worth reflecting on
        if not any(t.role == "user" for t in turns):
            return []

        conversation = _format_turns(turns, self._user_name, self._assistant_name)
        prompt = _EXTRACTION_PROMPT.format(conversation=conversation)

        raw = await self._complete(prompt)
        facts = parse_facts(raw, min_confidence=self._min_confidence)

        for fact in facts:
            self._store.remember(
                fact.text,
                kind=fact.kind,
                confidence=fact.confidence,
                source="reflection",
            )
        return facts

    async def reflect_recent(self, *, limit: int = 30) -> list[LearnedFact]:
        return await self.reflect(self._store.recent_turns(limit=limit))
