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
import urllib.parse
import urllib.request
from datetime import datetime
from typing import TYPE_CHECKING

from ..timeparse import parse_when

if TYPE_CHECKING:  # pragma: no cover
    from ..memory.store import MemoryStore
    from ..reminders import ReminderStore


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


def get_weather(city: str) -> str:
    """Fetch a short current-weather line from wttr.in (free, no API key)."""
    try:
        q = urllib.parse.quote(city.strip() or "")
        url = f"https://wttr.in/{q}?format=%l:+%c+%t,+sensacao+%f,+umidade+%h&m&lang=pt"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.read().decode("utf-8", "replace").strip()
    except Exception as exc:  # pragma: no cover - network dependent
        return f"Não consegui obter o clima agora: {exc}"


def media_control(action: str) -> str:
    """Best-effort media control on macOS (Music/Spotify) via AppleScript."""
    action = action.strip().lower()
    mapping = {
        "play": "playpause", "pause": "playpause", "toggle": "playpause",
        "next": "next track", "próxima": "next track", "proxima": "next track",
        "previous": "previous track", "anterior": "previous track",
    }
    cmd = mapping.get(action, "playpause")
    if platform.system() != "Darwin":  # pragma: no cover - platform dependent
        return "Controle de mídia só está disponível no macOS por enquanto."
    try:
        script = (
            f'if application "Spotify" is running then tell application "Spotify" to {cmd} '
            f'else tell application "Music" to {cmd}'
        )
        subprocess.Popen(["osascript", "-e", script])
        return f"Mídia: {action}."
    except Exception as exc:  # pragma: no cover
        return f"Falha no controle de mídia: {exc}"


def build_tool_server(store: "MemoryStore", reminder_store: "ReminderStore | None" = None):
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

    @tool("weather", "Consulta o clima atual de uma cidade.", {"city": str})
    async def weather_tool(args):  # noqa: ANN001
        return _text(get_weather(str(args.get("city", ""))))

    @tool(
        "media",
        "Controla a mídia (play/pause/próxima/anterior) no Music/Spotify.",
        {"action": str},
    )
    async def media_tool(args):  # noqa: ANN001
        return _text(media_control(str(args.get("action", "toggle"))))

    tools = [get_time, remember, recall, forget, open_tool, notify_tool, weather_tool, media_tool]
    allowed = [
        "mcp__zemark__get_time",
        "mcp__zemark__remember",
        "mcp__zemark__recall",
        "mcp__zemark__forget",
        "mcp__zemark__open",
        "mcp__zemark__notify",
        "mcp__zemark__weather",
        "mcp__zemark__media",
        # built-in Claude Code web tools — no API key required
        "WebSearch",
        "WebFetch",
    ]

    if reminder_store is not None:
        @tool(
            "set_reminder",
            "Cria um lembrete com horário. 'when' aceita linguagem natural em "
            "português: 'em 10 minutos', 'às 15h', 'amanhã às 9h'.",
            {"text": str, "when": str},
        )
        async def set_reminder(args):  # noqa: ANN001
            text = str(args.get("text", "")).strip()
            when = str(args.get("when", "")).strip()
            if not text or not when:
                return _text("Preciso do lembrete e de quando.")
            due = parse_when(when)
            if due is None:
                return _text("Não entendi o horário. Tente 'em 10 minutos' ou 'às 15h'.")
            reminder_store.add(text, due)
            quando = datetime.fromtimestamp(due).astimezone().strftime("%d/%m às %H:%M")
            return _text(f"Lembrete criado: {text} — {quando}.")

        @tool("list_reminders", "Lista os próximos lembretes pendentes.", {})
        async def list_reminders(args):  # noqa: ANN001
            items = reminder_store.upcoming(limit=10)
            if not items:
                return _text("Nenhum lembrete pendente.")
            lines = []
            for r in items:
                quando = datetime.fromtimestamp(r.due_ts).astimezone().strftime("%d/%m %H:%M")
                lines.append(f"- {quando}: {r.text}")
            return _text("\n".join(lines))

        @tool("cancel_reminder", "Cancela lembretes que casem com a descrição.", {"query": str})
        async def cancel_reminder(args):  # noqa: ANN001
            query = str(args.get("query", "")).strip()
            if not query:
                return _text("Preciso saber qual lembrete cancelar.")
            n = reminder_store.cancel_matching(query)
            return _text(f"Cancelei {n} lembrete(s).")

        tools += [set_reminder, list_reminders, cancel_reminder]
        allowed += [
            "mcp__zemark__set_reminder",
            "mcp__zemark__list_reminders",
            "mcp__zemark__cancel_reminder",
        ]

    server = create_sdk_mcp_server(name="zemark", version="1.0.0", tools=tools)
    return server, allowed
