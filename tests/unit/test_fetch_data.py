from pathlib import Path

from scripts.fetch_data import FILES, missing


def test_missing_lists_everything_when_directory_is_empty(tmp_path: Path) -> None:
    assert missing(tmp_path) == list(FILES)


def test_missing_counts_a_zero_length_file_as_absent(tmp_path: Path) -> None:
    for name in FILES:
        (tmp_path / name).write_text("header\n")
    (tmp_path / FILES[0]).write_text("")

    assert missing(tmp_path) == [FILES[0]]
