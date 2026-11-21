"""Code and configs carry no labels of how the work was done: card ids, audit ids, weekly
decision ids and dates. A comment keeps the reason and names an ADR where one applies; the
history stays in docs/ and git.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Cyrillic B and K (card prefixes) are written as escapes on purpose.
PATTERN = re.compile(
    r"\b(W[0-9](-[TD][0-9]+[ab]?)?|D[0-9]{1,2}"
    r"|(QA|SEC|REL|DATA|DOC|MODEL|ARCH|AI|PF|F|R)-[0-9]{2}"
    r"|RT-S[0-9]|[Bb\u0411\u041a][0-9]{1,2})\b"
    r"|[Aa]udit|[Ww]eek[ -][0-9]|verified 202"
    r"|[(, ]202[0-9]-[01][0-9]-[0-3][0-9]\b"
    r"|[(, ][0-3][0-9]\.(09|10|11)\b"
)

SKIP_PREFIXES = ("docs/", ".claude/", "data/sample/", "tests/unit/test_agent_")
SKIP_SUFFIXES = (".md", ".csv", ".svg", ".png", ".patch")
SKIP_FILES = {"uv.lock", "scripts/agent_state.py", "tests/unit/test_no_history_in_code.py"}

# (path, stripped line) pairs that match the pattern but are data, not work labels.
ALLOWED = {
    # Output of `java -version` fed to a parser; the date is the JDK release date.
    (
        "tests/unit/test_spark_jvm.py",
        """('openjdk version "25.0.5" 2026-04-21\\nOpenJDK Runtime Environment', 25),""",
    ),
    (
        "tests/unit/test_spark_jvm.py",
        """('openjdk version "17.0.21" 2026-04-21', 17),""",
    ),
}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [
        p
        for p in out.splitlines()
        if p not in SKIP_FILES and not p.startswith(SKIP_PREFIXES) and not p.endswith(SKIP_SUFFIXES)
    ]


def find_history_lines() -> list[str]:
    found: list[str] = []
    for rel in tracked_files():
        try:
            text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if PATTERN.search(line) and (rel, line.strip()) not in ALLOWED:
                found.append(f"{rel}:{number}: {line.strip()}")
    return found


def test_every_allowed_line_is_still_there() -> None:
    stale = [
        f"{rel}: {line}"
        for rel, line in sorted(ALLOWED)
        if line not in {raw.strip() for raw in (ROOT / rel).read_text("utf-8").splitlines()}
    ]
    assert not stale, "ALLOWED pairs whose line is gone:\n" + "\n".join(stale)


def test_code_and_configs_carry_no_work_history() -> None:
    found = find_history_lines()
    assert not found, f"{len(found)} lines with work labels:\n" + "\n".join(found)


@pytest.mark.parametrize(
    "text",
    [
        "(W5-D11)",
        "B3",
        "audit 30.10",
        "verified 2026-10-19",
        "(D8)",
        "SEC-02:",
        "week 4",
        "(23.10)",
    ],
)
def test_pattern_matches_work_labels(text: str) -> None:
    assert PATTERN.search(text)


@pytest.mark.parametrize(
    "text",
    [
        "ADR-025",
        "RELEASE.2025-09-07T16-13-09Z",
        "=2026-07-01",
        '"2026-10-09"',
        "Ubuntu 22.04",
        "Python 3.10",
        "UTF-16",
        "B2B",
    ],
)
def test_pattern_ignores_legitimate_text(text: str) -> None:
    assert not PATTERN.search(text)
