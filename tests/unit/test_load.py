from pathlib import Path

import pytest
from pydantic import ValidationError
from replayer.load import header_of, raw_dir
from replayer.settings import Settings


def test_header_of_strips_csv_quoting(tmp_path: Path) -> None:
    # Olist quotes its header but not every value; a naive split leaves the quotes attached
    # and the COPY column list then matches nothing.
    path = tmp_path / "quoted.csv"
    path.write_text('"order_id","order_status"\n"abc",delivered\n')

    assert header_of(path) == ["order_id", "order_status"]


def test_header_of_strips_byte_order_mark(tmp_path: Path) -> None:
    path = tmp_path / "bom.csv"
    path.write_text("﻿product_category_name,product_category_name_english\n")

    assert header_of(path) == ["product_category_name", "product_category_name_english"]


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    # Settings reads `.env` from the working directory: the developer's own file must not leak in.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.delenv("REPLAY_DATA", raising=False)
    return tmp_path


def test_raw_dir_takes_replay_data_from_dotenv(isolated: Path) -> None:
    (isolated / ".env").write_text("REPLAY_DATA=sample\n")

    assert raw_dir(Settings()) == Path("data") / "sample"


def test_raw_dir_defaults_to_data_raw(isolated: Path) -> None:
    assert raw_dir(Settings()) == Path("data") / "raw"


def test_replay_data_rejects_anything_but_raw_or_sample(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REPLAY_DATA", "bogus")

    with pytest.raises(ValidationError):
        Settings()
