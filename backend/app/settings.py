"""Настройки из переменных окружения. Подписанная ссылка и ключ не попадают в repr и логи."""

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
EVALUATOR_MODES = ("mock", "llm")
DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "openai": "gpt-6.1-sol"}
DEFAULT_DB_PATH = Path("data/cqa.sqlite3")
DEFAULT_CACHE_DIR = Path("data/cache")


@dataclass(frozen=True)
class Settings:
    """Созданные напрямую настройки не трогают диск и записи звонков: так работают тесты.

    Рабочие пути и замер длины записей включает load_settings.
    """

    dataset_url: str = field(default="", repr=False)
    evaluator: str = "mock"
    llm_provider: str = "anthropic"
    anthropic_api_key: str = field(default="", repr=False)
    openai_api_key: str = field(default="", repr=False)
    llm_model: str = DEFAULT_MODELS["anthropic"]
    price_input_per_mtok: float = 0.0
    price_output_per_mtok: float = 0.0
    db_path: Path | None = None
    cache_dir: Path | None = None
    measure_audio: bool = False
    batch_concurrency: int = 4


def _parse[T](env: Mapping[str, str], name: str, convert: Callable[[str], T], default: T) -> T:
    raw = env.get(name)
    if not raw:
        return default
    try:
        return convert(raw)
    except ValueError:
        raise ValueError(f"{name}: неверное значение {raw!r}") from None


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Без аргумента читает .env и окружение. В тестах окружение передаётся явно."""
    if env is None:
        load_dotenv(ROOT_DIR / ".env")
        env = os.environ

    defaults = Settings()
    evaluator = env.get("CQA_EVALUATOR") or defaults.evaluator
    if evaluator not in EVALUATOR_MODES:
        raise ValueError(f"CQA_EVALUATOR: ожидается одно из {EVALUATOR_MODES}, получено {evaluator!r}")

    provider = env.get("CQA_LLM_PROVIDER") or defaults.llm_provider
    if provider not in DEFAULT_MODELS:
        raise ValueError(f"CQA_LLM_PROVIDER: ожидается одно из {tuple(DEFAULT_MODELS)}, не {provider!r}")

    concurrency = _parse(env, "CQA_BATCH_CONCURRENCY", int, defaults.batch_concurrency)
    if concurrency < 1:
        raise ValueError("CQA_BATCH_CONCURRENCY: нужно число от 1")

    return Settings(
        dataset_url=env.get("CQA_DATASET_URL", ""),
        evaluator=evaluator,
        llm_provider=provider,
        anthropic_api_key=env.get("ANTHROPIC_API_KEY", ""),
        openai_api_key=env.get("OPENAI_API_KEY", ""),
        llm_model=env.get("CQA_LLM_MODEL") or DEFAULT_MODELS[provider],
        price_input_per_mtok=_parse(env, "CQA_PRICE_INPUT_PER_MTOK", float, 0.0),
        price_output_per_mtok=_parse(env, "CQA_PRICE_OUTPUT_PER_MTOK", float, 0.0),
        db_path=_parse(env, "CQA_DB_PATH", Path, DEFAULT_DB_PATH),
        cache_dir=_parse(env, "CQA_CACHE_DIR", Path, DEFAULT_CACHE_DIR),
        measure_audio=True,
        batch_concurrency=concurrency,
    )
