import pytest
from pydantic import ValidationError
from spark_jobs.settings import Settings


def test_rest_catalog_is_refused_until_w2_t09(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CATALOG_TYPE", "rest")

    with pytest.raises(ValidationError):
        Settings()


def test_trigger_and_offsets_come_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRONZE_TRIGGER_SECONDS", "10")
    monkeypatch.setenv("BRONZE_MAX_OFFSETS_PER_TRIGGER", "5000")

    settings = Settings()

    assert (settings.bronze_trigger_seconds, settings.bronze_max_offsets_per_trigger) == (10, 5000)
