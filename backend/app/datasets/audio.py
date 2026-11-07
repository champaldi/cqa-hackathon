"""Записи звонков. audio_url ведёт на страницу плеера, ссылка на файл в ней живёт недолго."""

import html
import re

import httpx

from backend.app.datasets.client import get_checked
from backend.app.errors import DatasetError

SOURCE = "Сервер записей"
SOURCE_TAG = re.compile(r'<source\b[^>]*\bsrc="([^"]+)"', re.IGNORECASE)
HEADER_BYTES = 8192
XING_SEARCH_BYTES = 64
XING_HAS_FRAMES = 1
LAYER_III = 1

# Ключ: версия MPEG из заголовка кадра.
SAMPLE_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}
SAMPLES_PER_FRAME = {3: 1152, 2: 576, 0: 576}


def _require_https(url: str) -> None:
    if not url.startswith("https://"):
        raise DatasetError("Ссылка на запись должна начинаться с https")


def fetch_audio_link(player_url: str, transport: httpx.BaseTransport | None = None) -> str:
    """Свежая ссылка на файл записи. Сама ссылка подписана, в логи и ошибки она не попадает."""
    _require_https(player_url)
    match = SOURCE_TAG.search(get_checked(player_url, SOURCE, transport).text)
    if match is None:
        raise DatasetError("На странице записи нет ссылки на файл")
    link = html.unescape(match.group(1))
    _require_https(link)
    return link


def fetch_audio_duration(player_url: str, transport: httpx.BaseTransport | None = None) -> float | None:
    """Длина записи по первым килобайтам файла, None если заголовка с длиной нет."""
    link = fetch_audio_link(player_url, transport)
    first_bytes = {"Range": f"bytes=0-{HEADER_BYTES - 1}"}
    return mp3_duration(get_checked(link, SOURCE, transport, first_bytes).content)


def _first_frame(data: bytes) -> int:
    """Файл может начинаться с тега ID3: его размер записан по 7 бит в байте."""
    if data[:3] != b"ID3" or len(data) < 10:
        return 0
    size = 0
    for byte in data[6:10]:
        size = size << 7 | byte & 0x7F
    return 10 + size


def mp3_duration(data: bytes) -> float | None:
    """Читает число кадров из заголовка Xing или Info в первом кадре файла."""
    start = _first_frame(data)
    header = data[start : start + 4]
    if len(header) < 4 or header[0] != 0xFF or header[1] & 0xE0 != 0xE0:
        return None
    version = header[1] >> 3 & 3
    layer = header[1] >> 1 & 3
    rate_index = header[2] >> 2 & 3
    if version not in SAMPLE_RATES or layer != LAYER_III or rate_index == 3:
        return None
    stop = start + XING_SEARCH_BYTES
    tag = max(data.find(b"Xing", start, stop), data.find(b"Info", start, stop))
    if tag < 0 or len(data) < tag + 12 or not data[tag + 7] & XING_HAS_FRAMES:
        return None
    frames = int.from_bytes(data[tag + 8 : tag + 12])
    return frames * SAMPLES_PER_FRAME[version] / SAMPLE_RATES[version][rate_index]
