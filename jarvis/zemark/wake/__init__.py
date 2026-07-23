"""Pluggable wake-word detection for 'ZEMARK'."""

from .factory import build_wake
from .phrase import PhraseMatcher

__all__ = ["build_wake", "PhraseMatcher"]
