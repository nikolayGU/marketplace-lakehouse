import re
import subprocess
from functools import cache
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

AGENTS = "AGENTS.md"
CLAUDE = "CLAUDE.md"
RULES = "docs/agent-rules.md"
HARNESS = "docs/planning/13-harness.md"
HANDOFF = "docs/HANDOFF.md"
NEXT = "docs/NEXT_SESSION.md"
SKILL = ".claude/skills/task/SKILL.md"

BYTE_BUDGETS = {
    AGENTS: 8192,
    CLAUDE: 2048,
    RULES: 6144,
    HARNESS: 15360,
    HANDOFF: 20480,
    NEXT: 4096,
}

ROLE_FILES = sorted((REPO / ".claude" / "agents").glob("*.md"))

# Paths the documents name although they do not exist (yet), with the reason.
MENTIONED_MISSING: dict[str, str] = {
    ".claude/settings.local.json": "owner-local settings file, kept out of git, so absent in CI",
}


def _frontmatter(path: Path) -> dict[str, object]:
    parts = path.read_text().split("\n---\n", 1)
    assert parts[0].startswith("---\n"), f"{path.name}: no frontmatter"
    # Line-wise on purpose: a description may hold ": " and is not valid YAML.
    data: dict[str, object] = {}
    for line in parts[0][4:].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.isidentifier():
            data[key] = value.strip()
    return data


def _tool_list(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, list):
        return {str(v).strip() for v in value}
    return {v.strip() for v in str(value).split(",") if v.strip()}


@pytest.mark.parametrize("name", list(BYTE_BUDGETS))
def test_agent_documents_fit_their_byte_budget(name: str) -> None:
    size = len((REPO / name).read_bytes())

    assert size <= BYTE_BUDGETS[name], f"{name}: {size} bytes, budget {BYTE_BUDGETS[name]}"


@pytest.mark.parametrize("role", ROLE_FILES, ids=lambda p: p.name)
def test_roles_set_model_turns_no_agent(role: Path) -> None:
    meta = _frontmatter(role)

    assert meta.get("model"), f"{role.name}: no model"
    assert meta.get("maxTurns"), f"{role.name}: no maxTurns"
    denied = _tool_list(meta.get("disallowedTools"))
    allowed = _tool_list(meta.get("tools")) if "tools" in meta else None
    no_agent = "Agent" in denied or (allowed is not None and "Agent" not in allowed)
    assert no_agent, f"{role.name}: a subagent could start subagents"


def test_auditor_role_reads_on_opus() -> None:
    path = REPO / ".claude" / "agents" / "auditor.md"
    assert path.exists(), "auditor.md is missing"
    meta = _frontmatter(path)

    assert meta.get("name") == "auditor"
    assert meta.get("model") == "opus"
    assert {"Agent", "Edit", "NotebookEdit"} <= _tool_list(meta.get("disallowedTools"))


def test_agents_md_lists_the_roles() -> None:
    text = (REPO / AGENTS).read_text()
    # The rule files wrap at 100 columns, so a role and its model may sit across a line break.
    listed = set(re.findall(r"`([\w-]+)`\s+\((Haiku|Sonnet|Opus)", text))
    roles = set()
    for role in ROLE_FILES:
        meta = _frontmatter(role)
        roles.add((str(meta["name"]), str(meta["model"]).capitalize()))

    assert listed == roles


LONG_DASHES = (chr(0x2013), chr(0x2014))
LONG_DASH_FILES = [AGENTS, CLAUDE, RULES, HARNESS, SKILL, HANDOFF, NEXT]


def test_rule_files_have_no_long_dash() -> None:
    paths = [REPO / n for n in LONG_DASH_FILES] + ROLE_FILES
    found = [
        f"{p.relative_to(REPO)}:{i}"
        for p in paths
        for i, line in enumerate(p.read_text().splitlines(), 1)
        if any(dash in line for dash in LONG_DASHES)
    ]

    assert not found, found


@cache
def _tracked_paths() -> frozenset[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return frozenset(out.splitlines())


def _exists(path: str) -> bool:
    path = path.rstrip("/")
    prefix = path + "/"
    return path in _tracked_paths() or any(p.startswith(prefix) for p in _tracked_paths())


PATH_DOCS = [AGENTS, CLAUDE, RULES, HARNESS, NEXT, SKILL]
PATH_ROOTS = ("docs/", ".claude/", "scripts/")
SKIP_CHARS = re.compile(r"[<*{|$\s]")
LINE_SUFFIX = re.compile(r":\d+(-\d+)?$")


def test_rule_paths_exist() -> None:
    missing = []
    for name in PATH_DOCS:
        for fragment in re.findall(r"`([^`\n]+)`", (REPO / name).read_text()):
            if not fragment.startswith(PATH_ROOTS) or SKIP_CHARS.search(fragment):
                continue
            path = LINE_SUFFIX.sub("", fragment)
            if path in MENTIONED_MISSING or _exists(path):
                continue
            missing.append(f"{path} (in {name})")

    assert not missing, "\n".join(sorted(set(missing)))


CLOSED_BLOCK = re.compile(r"\b(W6-D(3|4|13|15)|W6-T0[23]|W5-D13)\b")


def test_harness_names_no_closed_block() -> None:
    found = [
        f"{i}: {m.group(0)}"
        for i, line in enumerate((REPO / HARNESS).read_text().splitlines(), 1)
        for m in CLOSED_BLOCK.finditer(line)
    ]

    assert not found, found


def test_handoff_starts_with_state_section() -> None:
    headings = [
        line for line in (REPO / HANDOFF).read_text().splitlines() if line.startswith("## ")
    ]

    assert headings, "HANDOFF has no level 2 heading"
    assert headings[0].startswith("## Состояние"), headings[0]
