"""Public text reads cleanly: no long dashes, no personal home-directory names, no broken
relative links or anchors in Markdown. A leaked local path or a dead link is visible to every
reader of the repository, so the check runs with the unit tests.
"""

import contextlib
import getpass
import re
import subprocess
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

LONG_DASHES = (chr(0x2013), chr(0x2014))
HOME_PATH = re.compile(r"/home/([a-z_][a-z0-9_.-]*)/")
ALLOWED_HOME_NAMES = {"user", "nonroot", "runner", "root"}
NON_PERSONAL_NAMES = ALLOWED_HOME_NAMES | {
    "ubuntu",
    "debian",
    "admin",
    "vscode",
    "node",
    "codespace",
    "airflow",
    "postgres",
    "spark",
    "home",
    "jovyan",
    "ec2-user",
    "runneradmin",
}
GITHUB_ROUTES = ("actions/", "issues", "pulls", "releases", "blob/", "tree/", "wiki")

KEPT_CATEGORIES = {"Mn", "Nd", "Nl", "No"} | {f"L{c}" for c in "ultmo"}
FENCE = re.compile(r"^\s*(```|~~~)")
LINK = re.compile(r"!?\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def tracked_paths() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout
    return [p for p in out.decode().split("\0") if p]


def read_text(root: Path, rel: str) -> str | None:
    try:
        return (root / rel).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def tracked_text() -> list[tuple[str, list[str]]]:
    files = []
    for rel in tracked_paths():
        text = read_text(ROOT, rel)
        if text is not None:
            files.append((rel, text.splitlines()))
    return files


def strip_code(lines: list[str]) -> list[tuple[int, str]]:
    """Return (line number, text) with fenced blocks and inline code removed."""
    result = []
    in_fence = False
    for number, line in enumerate(lines, start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            result.append((number, re.sub(r"`[^`]*`", "``", line)))
    return result


def slugify(heading: str) -> str:
    """GitHub heading anchor: lowercase, spaces to hyphens, punctuation dropped."""
    text = re.sub(r"<[^>]+>", "", heading).replace("`", "")
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).strip().lower()
    out = []
    for ch in text:
        if ch == " ":
            out.append("-")
        elif ch in "-_" or unicodedata.category(ch) in KEPT_CATEGORIES:
            out.append(ch)
    return "".join(out)


def anchors(root: Path, rel: str) -> set[str]:
    found: set[str] = set()
    seen: dict[str, int] = {}
    in_fence = False
    for line in (read_text(root, rel) or "").splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if heading:
            base = slugify(heading.group(2))
            count = seen.get(base, 0)
            found.add(base if count == 0 else f"{base}-{count}")
            seen[base] = count + 1
        found.update(re.findall(r'<a\s+(?:name|id)="([^"]+)"', line))
    return found


def normalize(path: str) -> str:
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            else:
                parts.append("..")
        else:
            parts.append(part)
    return "/".join(parts)


def find_broken_links(root: Path, md_files: list[str], tracked: set[str]) -> list[str]:
    problems: list[str] = []
    for rel in md_files:
        text = read_text(root, rel)
        if text is None:
            continue
        for number, line in strip_code(text.splitlines()):
            for match in LINK.finditer(line):
                target = match.group(2)
                where = f"{rel}:{number}: {target}"
                if re.match(r"^[a-z]+:", target) or target.startswith("//"):
                    continue
                path, _, fragment = target.partition("#")
                dest = rel if path == "" else normalize(f"{Path(rel).parent.as_posix()}/{path}")
                if dest.startswith(".."):
                    prefix = "../" * (rel.count("/") + 2)
                    if not (
                        target.startswith(prefix)
                        and target[len(prefix) :].startswith(GITHUB_ROUTES)
                    ):
                        problems.append(f"{where} (GitHub-relative link needs prefix {prefix})")
                    continue
                full = root / dest
                if not full.exists():
                    problems.append(f"{where} (missing)")
                elif full.is_dir():
                    if not any(t.startswith(dest.rstrip("/") + "/") for t in tracked):
                        problems.append(f"{where} (directory has no tracked files)")
                elif dest not in tracked:
                    problems.append(f"{where} (not tracked)")
                elif fragment:
                    if dest.endswith(".md"):
                        if fragment not in anchors(root, dest):
                            problems.append(f"{where} (no such anchor)")
                    elif not re.match(r"L\d+", fragment):
                        problems.append(f"{where} (unsupported fragment)")
    return problems


def test_no_long_dash_in_tracked_text() -> None:
    found = [
        f"{rel}:{number}"
        for rel, lines in tracked_text()
        for number, line in enumerate(lines, start=1)
        if any(dash in line for dash in LONG_DASHES)
    ]
    assert not found, f"{len(found)} lines with a long dash:\n" + "\n".join(found)


def environment_names() -> set[str]:
    names = {Path.home().name}
    with contextlib.suppress(Exception):
        names.add(getpass.getuser())
    return {n.lower() for n in names if len(n) > 3 and n.lower() not in NON_PERSONAL_NAMES}


def find_name_leaks(files: list[tuple[str, list[str]]], names: set[str] | None = None) -> list[str]:
    """Findings as `path[:line]: rule`; the matched name is never part of the output."""
    watched = environment_names() if names is None else names

    def mask(text: str) -> str:
        for name in watched:
            text = re.sub(re.escape(name), "***", text, flags=re.IGNORECASE)
        return text

    def leaks_name(text: str) -> bool:
        lowered = text.lower()
        return any(name in lowered for name in watched)

    def leaks_home(text: str) -> bool:
        return any(m.group(1) not in ALLOWED_HOME_NAMES for m in HOME_PATH.finditer(text))

    findings: list[str] = []
    for rel, lines in files:
        shown = mask(rel)
        if leaks_home("/" + rel):
            findings.append(f"{shown}: home path in file name")
        if leaks_name(rel):
            findings.append(f"{shown}: environment user name in file name")
        for number, line in enumerate(lines, start=1):
            if leaks_home(line):
                findings.append(f"{shown}:{number}: home path")
            if leaks_name(line):
                findings.append(f"{shown}:{number}: environment user name")
    return findings


def test_no_home_directory_name_in_tracked_files() -> None:
    found = find_name_leaks(tracked_text())
    assert not found, f"{len(found)} personal path or name findings:\n" + "\n".join(found)


def test_relative_links_and_anchors_resolve() -> None:
    tracked = set(tracked_paths())
    md_files = sorted(
        p for p in tracked if p.endswith(".md") and not p.startswith("docs/planning/")
    )
    problems = find_broken_links(ROOT, md_files, tracked)
    assert not problems, f"{len(problems)} broken links:\n" + "\n".join(problems)


def test_link_checker_finds_a_broken_link_and_anchor(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text(
        "[gone](missing.md)\n"
        "[bad anchor](b.md#no-such-heading)\n"
        "[fine](b.md#real-heading)\n"
        "`[in code](missing.md)`\n",
        encoding="utf-8",
    )
    (tmp_path / "b.md").write_text("## Real heading\n", encoding="utf-8")
    problems = find_broken_links(tmp_path, ["a.md", "b.md"], {"a.md", "b.md"})
    assert len(problems) == 2


def link_problems(tmp_path: Path, files: dict[str, str], check: str) -> list[str]:
    for rel, text in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return find_broken_links(tmp_path, [check], set(files))


def test_link_to_repo_file_through_two_levels_up_is_valid(tmp_path: Path) -> None:
    files = {"README.md": "# Top\n", "docs/runbooks/a.md": "[x](../../README.md)\n"}
    assert link_problems(tmp_path, files, "docs/runbooks/a.md") == []


def test_link_escaping_the_repo_without_a_route_is_a_finding(tmp_path: Path) -> None:
    files = {"README.md": "# Top\n", "docs/x.md": "[x](../../../README.md)\n"}
    problems = link_problems(tmp_path, files, "docs/x.md")
    assert len(problems) == 1
    assert "docs/x.md:1: ../../../README.md" in problems[0]
    assert "GitHub-relative" in problems[0]


def test_github_route_with_correct_depth_is_valid(tmp_path: Path) -> None:
    top = link_problems(tmp_path, {"a.md": "[r](../../actions/runs/1)\n"}, "a.md")
    nested = link_problems(tmp_path, {"docs/x.md": "[r](../../../actions/runs/1)\n"}, "docs/x.md")
    assert top == []
    assert nested == []


def test_github_route_with_wrong_depth_is_a_finding(tmp_path: Path) -> None:
    files = {"docs/x.md": "[r](../../actions/runs/1)\n"}
    problems = link_problems(tmp_path, files, "docs/x.md")
    assert len(problems) == 1
    assert "prefix ../../../" in problems[0]


def test_in_repo_path_with_actions_runs_goes_through_file_check(tmp_path: Path) -> None:
    problems = link_problems(tmp_path, {"a.md": "[r](docs/actions/runs/1)\n"}, "a.md")
    assert len(problems) == 1
    assert "(missing)" in problems[0]


def test_directory_link_needs_tracked_files(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    files = {"a.md": "[d](docs/)\n[e](empty/)\n", "docs/b.md": "# B\n"}
    problems = link_problems(tmp_path, files, "a.md")
    assert len(problems) == 1
    assert "a.md:2: empty/" in problems[0]
    assert "directory has no tracked files" in problems[0]


def test_name_helper_reports_rules_without_the_name(tmp_path: Path) -> None:
    fake = "zorblax"
    files = [
        ("notes.txt", ["fine", f"hello {fake.upper()}", "/home/" + fake + "/data/x"]),
        (f"{fake}.txt", ["clean"]),
        ("ok.txt", ["/home/runner/work/x", "nothing here"]),
    ]
    findings = find_name_leaks(files, {fake})
    assert "notes.txt:2: environment user name" in findings
    assert "notes.txt:3: home path" in findings
    assert "notes.txt:3: environment user name" in findings
    assert any(f.endswith(": environment user name in file name") for f in findings)
    assert not any(f.startswith("ok.txt") for f in findings)
    assert fake not in "\n".join(findings).lower()


def test_environment_names_skip_common_account_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: Path("/home/ubuntu"))
    monkeypatch.setattr(getpass, "getuser", lambda: "codespace")
    assert environment_names() == set()
