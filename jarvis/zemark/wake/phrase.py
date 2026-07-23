"""Phrase-based wake detection — the zero-setup default backend.

A made-up wake word like "ZEMARK" has no pretrained model, and training one
(openWakeWord/Colab) or minting a Porcupine ``.ppn`` is optional polish. This
backend needs neither: it runs short STT transcriptions and fuzzy-matches the
wake word in the text, so ZEMARK answers on day one.

Speech-to-text routinely mangles invented names ("zi mark", "zé marky"…), so
matching is accent-insensitive and fuzzy, with a configurable alias list.
Everything here is pure text logic — no audio deps — so it is fully unit-tested.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher


def _normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    cleaned = [c if c.isalnum() or c.isspace() else " " for c in text]
    return " ".join("".join(cleaned).split())


@dataclass
class PhraseMatcher:
    word: str
    aliases: tuple[str, ...] = ()
    fuzzy_threshold: float = 0.82

    def __post_init__(self) -> None:
        forms = {self.word, *self.aliases}
        self._norm_forms = {n for n in (_normalize(f) for f in forms) if n}
        # the tightest single-token target, used for token-level fuzzy checks
        self._targets = sorted(self._norm_forms, key=len)

    def matches(self, text: str) -> bool:
        """True if the wake word appears in ``text`` (exact, alias, or fuzzy)."""
        norm = _normalize(text)
        if not norm:
            return False

        # 1) direct / alias substring hit
        for form in self._norm_forms:
            if form and form in norm:
                return True

        # 2) fuzzy match against each token and adjacent bigrams (STT drift)
        tokens = norm.split()
        candidates = list(tokens)
        candidates += [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]
        for cand in candidates:
            for target in self._targets:
                if _ratio(cand, target) >= self.fuzzy_threshold:
                    return True
        return False

    def strip_wake(self, text: str) -> str:
        """Remove a leading wake word so the remainder can be treated as the
        actual command (e.g. "zemark que horas são" -> "que horas são"). Handles
        multi-token wake forms like "zé mark"."""
        norm_tokens = _normalize(text).split()
        orig_tokens = text.split()
        if not norm_tokens:
            return text.strip()
        # try the longest leading span first so "ze mark" is stripped as one
        # unit, but only accept an exact or fuzzy match of the whole span — never
        # a mere prefix, so "zemark que horas" doesn't swallow the command.
        for span in (min(3, len(norm_tokens)), 2, 1):
            if span > len(norm_tokens):
                continue
            joined = " ".join(norm_tokens[:span])
            if any(joined == t or _ratio(joined, t) >= self.fuzzy_threshold for t in self._targets):
                return " ".join(orig_tokens[span:]).strip()
        return text.strip()


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()
