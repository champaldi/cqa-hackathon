"""Время реплик: смещение от начала диалога и положение на записи звонка.

Исходные метки не меняются. Начало записи в транскрипте не отмечено, поэтому положение
считается от её конца. Константы подобраны по записям.
"""

from datetime import datetime

from backend.app.contracts import Dialog, Turn

RECORDING_END_LAG_SEC = 2.2
SPEECH_CHARS_PER_SEC = 15.0


def _clock_seconds(timestamp: str) -> float | None:
    """Метка чата: MM:SS или HH:MM:SS."""
    parts = timestamp.split(":")
    if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return float(seconds)


def _iso_seconds(timestamp: str) -> float | None:
    """Метка звонка: ISO 8601 с часовым поясом."""
    try:
        return datetime.fromisoformat(timestamp).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def _seconds(timestamp: str) -> float | None:
    clock = _clock_seconds(timestamp)
    return _iso_seconds(timestamp) if clock is None else clock


def _speech_sec(turn: Turn) -> float:
    return len(turn.text) / SPEECH_CHARS_PER_SEC


def _timed(turn: Turn, value: float, start: float, end: float, has_recording: bool) -> Turn:
    update = {"offset_sec": round(value - start, 3)}
    if has_recording:
        update["audio_tail_sec"] = round(end - value + RECORDING_END_LAG_SEC + _speech_sec(turn), 3)
    return turn.model_copy(update=update)


def with_timing(dialog: Dialog) -> Dialog:
    """Реплика с непонятной меткой остаётся без смещений, диалог при этом не отбрасывается."""
    seconds = [_seconds(turn.timestamp) for turn in dialog.transcript]
    known = [value for value in seconds if value is not None]
    if not known:
        return dialog
    start, end = known[0], known[-1]
    has_recording = dialog.audio_url is not None
    transcript = [
        turn if value is None else _timed(turn, value, start, end, has_recording)
        for turn, value in zip(dialog.transcript, seconds, strict=True)
    ]
    return dialog.model_copy(update={"transcript": transcript})


def _position(turn: Turn, duration_sec: float) -> float | None:
    if turn.audio_tail_sec is None:
        return None
    position = duration_sec - turn.audio_tail_sec
    if position + _speech_sec(turn) <= 0:
        return None  # реплика закончилась до начала записи
    return round(max(position, 0.0), 3)


def with_audio_positions(dialog: Dialog, duration_sec: float) -> Dialog:
    """Заполняет audio_offset_sec, когда длина записи известна."""
    transcript = [
        turn.model_copy(update={"audio_offset_sec": _position(turn, duration_sec)})
        for turn in dialog.transcript
    ]
    return dialog.model_copy(update={"transcript": transcript})
