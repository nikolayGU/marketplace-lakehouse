import json
from pathlib import Path

from scripts.obs import check_dashboards


def _dashboard(path: Path, panels: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps({"title": "t", "panels": panels}))
    return path


def test_every_panel_with_data_passes(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = _dashboard(
        tmp_path / "a.json",
        [{"title": "lag", "targets": [{"expr": "up"}, {"expr": "sum(up)"}]}],
    )

    code = check_dashboards.check([path], lambda expr: [{"metric": {}, "value": [0, "1"]}])

    assert code == 0
    assert "panels ok: 2" in capsys.readouterr().out


def test_an_empty_result_fails_and_names_the_panel(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = _dashboard(tmp_path / "a.json", [{"title": "typo", "targets": [{"expr": "upp"}]}])

    code = check_dashboards.check([path], lambda expr: [])

    out = capsys.readouterr().out
    assert code == 1
    assert "typo" in out and "upp" in out


def test_a_panel_without_targets_does_not_crash(tmp_path: Path) -> None:
    path = _dashboard(tmp_path / "a.json", [{"title": "text"}, {"title": "row", "targets": []}])

    assert check_dashboards.check([path], lambda expr: []) == 0


def test_nested_row_panels_are_checked(tmp_path: Path) -> None:
    row: dict[str, object] = {
        "title": "row",
        "type": "row",
        "panels": [{"title": "p", "targets": [{"expr": "x"}]}],
    }
    path = _dashboard(tmp_path / "a.json", [row])

    assert check_dashboards.check([path], lambda expr: []) == 1


def test_a_failed_query_counts_as_empty(tmp_path: Path) -> None:
    path = _dashboard(tmp_path / "a.json", [{"title": "p", "targets": [{"expr": "x"}]}])

    def broken(expr: str) -> list[dict[str, object]]:
        raise OSError("prometheus down")

    assert check_dashboards.check([path], broken) == 1
