"""Транскрипт для модели: разделённый блок, строки `[index] speaker: text`."""

from __future__ import annotations

from ..contracts import Turn

OPEN = "<transcript>"
CLOSE = "</transcript>"
_ESCAPED_OPEN = "<\\transcript>"
_ESCAPED_CLOSE = "<\\/transcript>"
_CONTINUATION = "    "


def escape(text: str) -> str:
    """Разделители внутри реплики экранируются, перевод строки не может начать новую реплику."""
    text = text.replace(CLOSE, _ESCAPED_CLOSE).replace(OPEN, _ESCAPED_OPEN)
    return text.replace("\r\n", "\n").replace("\n", "\n" + _CONTINUATION)


def unescape(text: str) -> str:
    """Обратное преобразование разделителей: модель могла процитировать экранированный вид."""
    return text.replace(_ESCAPED_CLOSE, CLOSE).replace(_ESCAPED_OPEN, OPEN)


def render_transcript(turns: list[Turn]) -> str:
    lines = [OPEN]
    lines.extend(f"[{t.index}] {t.speaker}: {escape(t.text)}" for t in turns)
    lines.append(CLOSE)
    return "\n".join(lines)
