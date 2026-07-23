"""ZEMARK's reasoning engine.

Only :class:`ClaudeBrain` is exported here; the Pipecat ``LLMService`` adapter
lives in ``pipecat_llm`` and is imported by the pipeline module so that importing
the brain never requires Pipecat to be installed.
"""

from .claude_brain import ClaudeBrain

__all__ = ["ClaudeBrain"]
