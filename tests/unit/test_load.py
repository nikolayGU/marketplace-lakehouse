from pathlib import Path

from replayer.load import header_of


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
