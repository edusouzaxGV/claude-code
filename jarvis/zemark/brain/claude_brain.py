"""ZEMARK's reasoning engine, backed by the Claude Agent SDK.

Key properties:
    * **Subscription auth.** Runs on a Claude Pro/Max plan via the CLI OAuth
      token (``CLAUDE_CODE_OAUTH_TOKEN``) — no paid API key. On start we scrub
      ``ANTHROPIC_API_KEY`` from the process env, because it silently outranks
      the subscription token and would bill you per request.
    * **Persistent dialogue.** A single long-lived ``ClaudeSDKClient`` keeps
      conversational context across turns (good for follow-ups and barge-in),
      avoiding the subprocess spin-up cost of one-shot ``query()`` per turn.
    * **Streaming.** :meth:`ask` yields text as it arrives so TTS can start
      speaking almost immediately.
    * **Tools.** The in-process ZEMARK tool server plus Claude Code's built-in
      web tools are wired in, gated by an allow-list.

The SDK is imported lazily so this module imports fine without it installed
(tests stub the brain).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from ..config import Config
from ..persona import build_system_prompt


class ClaudeBrain:
    def __init__(self, cfg: Config, tool_server=None, allowed_tools: list[str] | None = None):
        self._cfg = cfg
        self._tool_server = tool_server
        self._allowed_tools = allowed_tools or []
        self._client = None  # ClaudeSDKClient, created in start()
        self._connected = False

    # -- lifecycle --------------------------------------------------------
    async def start(self) -> None:
        if self._cfg.brain.force_subscription_auth:
            # ANTHROPIC_API_KEY wins over the OAuth token in the SDK's credential
            # resolution — remove it so the subscription is actually used.
            os.environ.pop("ANTHROPIC_API_KEY", None)

        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient  # lazy

        options = ClaudeAgentOptions(
            system_prompt=build_system_prompt(self._cfg, memories=None),
            model=self._cfg.brain.model,
            permission_mode=self._cfg.brain.permission_mode,
            allowed_tools=self._allowed_tools,
            mcp_servers={"zemark": self._tool_server} if self._tool_server else {},
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()
        self._connected = True

    async def aclose(self) -> None:
        if self._client is not None and self._connected:
            try:
                await self._client.disconnect()
            finally:
                self._connected = False

    async def __aenter__(self) -> "ClaudeBrain":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    # -- interaction ------------------------------------------------------
    async def ask(self, user_text: str, memories: list[str] | None = None) -> AsyncIterator[str]:
        """Stream ZEMARK's spoken reply to a user utterance.

        Recalled memories are injected as a lightweight per-turn preface so the
        persistent dialogue stays personalised without rebuilding the whole
        system prompt each time.
        """
        if not self._connected:
            raise RuntimeError("ClaudeBrain.start() must be called before ask().")

        prompt = user_text
        if memories:
            preface = "  \n".join(f"- {m}" for m in memories)
            prompt = f"[memória relevante:\n{preface}\n]\n\n{user_text}"

        await self._client.query(prompt)
        async for chunk in self._stream_text(self._client.receive_response()):
            yield chunk

    async def complete(self, prompt: str) -> str:
        """One-shot, stateless completion for reflection / proactive drafting.

        Uses a fresh ``query()`` so it never pollutes the live dialogue context.
        Tools are disabled to keep it fast and deterministic.
        """
        from claude_agent_sdk import ClaudeAgentOptions, query  # lazy

        options = ClaudeAgentOptions(
            model=self._cfg.brain.model,
            permission_mode="bypassPermissions",
            allowed_tools=[],
            max_turns=1,
        )
        parts: list[str] = []
        async for message in query(prompt=prompt, options=options):
            parts.extend(_text_blocks(message))
        return "".join(parts).strip()

    # -- helpers ----------------------------------------------------------
    @staticmethod
    async def _stream_text(messages) -> AsyncIterator[str]:
        async for message in messages:
            for block in _text_blocks(message):
                if block:
                    yield block


def _text_blocks(message) -> list[str]:
    """Extract text from an AssistantMessage regardless of minor SDK shape drift."""
    out: list[str] = []
    content = getattr(message, "content", None)
    if content is None:
        return out
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            out.append(text)
    return out
