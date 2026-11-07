import pytest

from backend.app.settings import Settings, load_settings


def test_defaults_work_without_any_configuration() -> None:
    settings = load_settings({})

    assert settings.evaluator == "mock"
    assert settings.dataset_url == ""


def test_environment_overrides_defaults() -> None:
    settings = load_settings({"CQA_EVALUATOR": "llm", "CQA_BATCH_CONCURRENCY": "8"})

    assert settings.evaluator == "llm"
    assert settings.batch_concurrency == 8


def test_unknown_evaluator_is_rejected() -> None:
    with pytest.raises(ValueError, match="CQA_EVALUATOR"):
        load_settings({"CQA_EVALUATOR": "magic"})


def test_concurrency_must_be_positive() -> None:
    with pytest.raises(ValueError, match="CQA_BATCH_CONCURRENCY"):
        load_settings({"CQA_BATCH_CONCURRENCY": "0"})


def test_concurrency_must_be_a_number() -> None:
    with pytest.raises(ValueError, match="CQA_BATCH_CONCURRENCY"):
        load_settings({"CQA_BATCH_CONCURRENCY": "много"})


def test_repr_hides_signed_url_and_api_key() -> None:
    text = repr(Settings(dataset_url="https://api.test/?sig=secret", anthropic_api_key="sk-secret"))

    assert "secret" not in text
