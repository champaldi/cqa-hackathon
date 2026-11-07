"""Транскрипт для модели: разделённый блок, строки `[index] speaker: text`."""

from __future__ import annotations

from ..contracts import Turn

OPEN = "<transcript>"
CLOSE = "</transcript>"
_ESCAPED_OPEN = "<\\transcript>"
_ESCAPED_CLOSE = "<\\/transcript>"


def escape(text: str) -> str:
    """Разделители внутри реплики экранируются, переводы строк становятся пробелами.

    Одна реплика всегда занимает одну строку, поэтому текст не может изобразить новую реплику.
    """
    text = text.replace(CLOSE, _ESCAPED_CLOSE).replace(OPEN, _ESCAPED_OPEN)
    return " ".join(text.splitlines())


def unescape(text: str) -> str:
    """Обратное преобразование разделителей: модель могла процитировать экранированный вид."""
    return text.replace(_ESCAPED_CLOSE, CLOSE).replace(_ESCAPED_OPEN, OPEN)


def format_time(turn: Turn) -> str:
    """offset_sec как MM:SS, иначе исходный timestamp (обезвреженный: он тоже внешний ввод)."""
    if turn.offset_sec is not None:
        total = max(int(turn.offset_sec), 0)
        return f"{total // 60:02d}:{total % 60:02d}"
    return escape(turn.timestamp).replace("(", "").replace(")", "").strip()


def render_transcript(turns: list[Turn]) -> str:
    """Строка реплики: `[index] speaker (время): текст`."""
    lines = [OPEN]
    lines.extend(f"[{t.index}] {t.speaker} ({format_time(t)}): {escape(t.text)}" for t in turns)
    lines.append(CLOSE)
    return "\n".join(lines)
