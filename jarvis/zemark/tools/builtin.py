"""In-process tools ZEMARK's brain can call.

These run *inside* the Python process via the Claude Agent SDK's in-process MCP
server (`create_sdk_mcp_server`), so there is no subprocess and no network hop.
They are the hands of the assistant: telling time, reading/writing its own
memory, opening things on the machine, and surfacing desktop notifications.

Web search is intentionally NOT a custom tool here — the Claude Agent SDK brain
is allowed to use Claude Code's built-in ``WebSearch`` / ``WebFetch`` tools,
which need no extra API key.

The SDK is imported lazily inside :func:`build_tool_server` so that importing
this module (e.g. in tests) never requires ``claude-agent-sdk`` to be present.
"""

from __future__ import annotations

import platform
import subprocess
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from ..memory.store import MemoryStore


def _text(content: str) -> dict:
    """Shape a tool result the way the SDK expects."""
    return {"content": [{"type": "text", "text": content}]}


def open_target(target: str) -> str:
    """Open a URL, file, or application using the OS default handler."""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", target])
        elif system == "Windows":  # pragma: no cover - not our target
            subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)
        else:  # Linux
            subprocess.Popen(["xdg-open", target])
        return f"Abri: {target}"
    except Exception as exc:  # pragma: no cover - platform dependent
        return f"Não consegui abrir {target}: {exc}"


def notify(title: str, message: str) -> str:
    """Show a native desktop notification (best-effort, macOS-focused)."""
    system = platform.system()
    try:
        if system == "Darwin":
            script = f'display notification "{message}" with title "{title}"'
            subprocess.Popen(["osascript", "-e", script])
        else:  # pragma: no cover - platform dependent
            subprocess.Popen(["notify-send", title, message])
        return "Notificação enviada."
    except Exception as exc:  # pragma: no cover
        return f"Falha ao notificar: {exc}"


def build_tool_server(store: "MemoryStore"):
    """Create the in-process MCP server + the list of allowed tool names.

    Returns ``(server, allowed_tool_names)``. ``allowed_tool_names`` also
    includes the built-in Claude Code web tools so the brain can search online
    without any API key.
    """
    from claude_agent_sdk import create_sdk_mcp_server, tool  # lazy

    @tool("get_time", "Retorna a data e hora atuais no fuso local.", {})
    async def get_time(args):  # noqa: ANN001
        now = datetime.now().astimezone()
        return _text(now.strftime("Agora são %H:%M de %A, %d/%m/%Y (%Z)."))

    @tool(
        "remember",
        "Guarda um fato durável sobre o usuário na memória de longo prazo.",
        {"text": str, "kind": str},
    )
    async def remember(args):  # noqa: ANN001
        text = str(args.get("text", "")).strip()
        if not text:
            return _text("Nada para lembrar.")
        kind = str(args.get("kind", "fact")).strip() or "fact"
        store.remember(text, kind=kind, confidence=0.9, source="explicit")
        return _text(f"Anotado: {text}")

    @tool(
        "recall",
        "Busca na memória de longo prazo o que se sabe sobre um assunto.",
        {"query": str},
    )
    async def recall(args):  # noqa: ANN001
        query = str(args.get("query", "")).strip()
        hits = store.recall(query, limit=6) if query else store.recent(limit=6)
        if not hits:
            return _text("Não encontrei nada na memória sobre isso.")
        return _text("\n".join(f"- {m.text}" for m in hits))

    @tool(
        "forget",
        "Remove da memória tudo que casar com a descrição dada.",
        {"query": str},
    )
    async def forget(args):  # noqa: ANN001
        query = str(args.get("query", "")).strip()
        if not query:
            return _text("Preciso saber o que esquecer.")
        removed = store.forget_matching(query)
        return _text(f"Removi {removed} memória(s).")

    @tool("open", "Abre uma URL, arquivo ou aplicativo no computador.", {"target": str})
    async def open_tool(args):  # noqa: ANN001
        target = str(args.get("target", "")).strip()
        if not target:
            return _text("Preciso do que abrir.")
        return _text(open_target(target))

    @tool(
        "notify",
        "Mostra uma notificação nativa na área de trabalho.",
        {"title": str, "message": str},
    )
    async def notify_tool(args):  # noqa: ANN001
        return _text(notify(str(args.get("title", "ZEMARK")), str(args.get("message", ""))))

    server = create_sdk_mcp_server(
        name="zemark",
        version="1.0.0",
        tools=[get_time, remember, recall, forget, open_tool, notify_tool],
    )

    allowed = [
        "mcp__zemark__get_time",
        "mcp__zemark__remember",
        "mcp__zemark__recall",
        "mcp__zemark__forget",
        "mcp__zemark__open",
        "mcp__zemark__notify",
        # built-in Claude Code web tools — no API key required
        "WebSearch",
        "WebFetch",
    ]
    return server, allowed
