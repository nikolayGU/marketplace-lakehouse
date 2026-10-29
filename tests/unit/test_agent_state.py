import subprocess
import sys
from pathlib import Path

import pytest

from scripts.agent_state import (
    ACCEPTED,
    CHECK_COMMAND,
    CHECK_STAMP,
    CODE,
    REVIEW_STAMP,
    STAMP,
    VERDICTS,
    code_changes,
    code_changes_since,
    describe_stamp,
    read_stamp,
    record_review,
    run_check,
    tree_hash,
    write_stamp,
)

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "agent_state.py"
WITH_NOTES = "принять с замечаниями"  # noqa: RUF001


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.invalid")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text(".verify-stamp\n.check-stamp\n.review-stamp\ntarget/\n")
    (tmp_path / "job.py").write_text("x = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_tree_hash_follows_content_not_staging_or_commits(repo: Path) -> None:
    clean = tree_hash(repo)
    (repo / "job.py").write_text("x = 2\n")
    edited = tree_hash(repo)
    (repo / "new.py").write_text("y = 1\n")
    untracked = tree_hash(repo)
    git(repo, "add", ".")
    staged = tree_hash(repo)
    git(repo, "commit", "-q", "-m", "next")

    assert len({clean, edited, untracked}) == 3
    assert staged == untracked == tree_hash(repo)
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True
        ).stdout
        == ""
    )


def test_tree_hash_ignores_gitignored_files(repo: Path) -> None:
    before = tree_hash(repo)
    (repo / "target").mkdir()
    (repo / "target" / "out.json").write_text("{}")
    (repo / ".verify-stamp").write_text("anything")

    assert tree_hash(repo) == before


def test_stamp_is_fresh_only_for_the_tree_it_was_written_for(repo: Path) -> None:
    write_stamp(repo, "fast")
    stamp = read_stamp(repo)
    assert stamp is not None and stamp.mode == "fast" and stamp.fresh

    (repo / "job.py").write_text("x = 3\n")
    stale = read_stamp(repo)
    assert stale is not None and not stale.fresh


def test_missing_or_garbled_stamp_reads_as_none(repo: Path) -> None:
    assert read_stamp(repo) is None
    (repo / ".verify-stamp").write_text("garbage\n")
    assert read_stamp(repo) is None


def test_write_stamp_refuses_an_unknown_mode(repo: Path) -> None:
    with pytest.raises(ValueError, match="mode"):
        write_stamp(repo, "partial")


def test_code_changes_skip_markdown_and_docs(repo: Path) -> None:
    (repo / "docs").mkdir()
    (repo / "docs" / "plan.txt").write_text("x")
    (repo / "README.md").write_text("x")
    assert code_changes(repo) == []

    (repo / "job.py").write_text("x = 4\n")
    assert code_changes(repo) == ["job.py"]


def test_describe_stamp(repo: Path) -> None:
    assert describe_stamp(repo) == "none"
    write_stamp(repo, "full")
    assert describe_stamp(repo).startswith("full at ") and describe_stamp(repo).endswith("fresh")
    (repo / "job.py").write_text("x = 5\n")
    assert describe_stamp(repo).endswith("stale")


def test_cli_refuses_an_unknown_command(repo: Path) -> None:
    result = subprocess.run([sys.executable, str(SCRIPT), "erase", str(repo)], capture_output=True)
    assert result.returncode != 0


def test_cli_writes_a_stamp(repo: Path) -> None:
    subprocess.run([sys.executable, str(SCRIPT), "stamp", "full", str(repo)], check=True)
    stamp = read_stamp(repo)

    assert stamp is not None and stamp.mode == "full" and stamp.fresh


def test_changes_since_the_stamp_are_listed_by_path(repo: Path) -> None:
    write_stamp(repo, "full")
    (repo / "NOTES.md").write_text("x")
    (repo / "docs").mkdir()
    (repo / "docs" / "a.txt").write_text("y")
    stamp = read_stamp(repo)

    assert stamp is not None and not stamp.fresh
    assert code_changes_since(repo, stamp) == []

    (repo / "job.py").write_text("x = 9\n")
    assert code_changes_since(repo, stamp) == ["job.py"]


WIDE_NOTES = "принять \t с   замечаниями"  # noqa: RUF001


def git_out(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def cli(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


def lines(*parts: str) -> str:
    return "".join(f"{part}\n" for part in parts)


def reviewer_report(verdict: str, tree: str, subject: str = CODE) -> str:
    """A report as the reviewer role writes it: verdict and subject first, the tree id line last."""
    return lines(
        f"Вердикт: {verdict}",
        f"Предмет: {subject}",
        "| # | серьёзность | файл:строка |",
        "Проверено и чисто: make test",
        f"Дерево: {tree}",
    )


def assert_revoked(repo: Path, message: str) -> None:
    stamp = read_stamp(repo, "review")
    assert message.startswith("review stamp revoked")
    assert stamp is not None and (stamp.mode, stamp.tree) == ("return", tree_hash(repo))


def test_check_stamp_is_kept_apart_from_the_verify_stamp(repo: Path) -> None:
    write_stamp(repo, "check")

    assert (repo / CHECK_STAMP).exists()
    assert not (repo / STAMP).exists()
    check = read_stamp(repo, "check")
    assert check is not None and check.mode == "check" and check.fresh
    assert read_stamp(repo) is None
    assert read_stamp(repo, "review") is None

    write_stamp(repo, "fast")
    verify = read_stamp(repo)
    assert verify is not None and verify.mode == "fast"
    (repo / "job.py").write_text("x = 6\n")
    stale = read_stamp(repo, "check")
    assert stale is not None and not stale.fresh
    assert describe_stamp(repo, "check").endswith("stale")
    assert describe_stamp(repo, "review") == "none"


@pytest.mark.parametrize(
    ("kind", "mode", "readable"),
    [
        ("verify", "full", True),
        ("verify", "check", False),
        ("verify", "accept", False),
        ("check", "check", True),
        ("check", "full", False),
        ("review", "accept", True),
        ("review", "accept-with-notes", True),
        ("review", "return", True),
        ("review", "fast", False),
        ("review", "check", False),
    ],
)
def test_a_stamp_holds_only_the_modes_of_its_kind(
    repo: Path, kind: str, mode: str, readable: bool
) -> None:
    name = {"verify": STAMP, "check": CHECK_STAMP, "review": REVIEW_STAMP}[kind]
    (repo / name).write_text(f"{mode} 2026-10-29T10:00:00Z {tree_hash(repo)}\n")

    assert (read_stamp(repo, kind) is not None) is readable


def test_an_unknown_stamp_kind_is_an_error(repo: Path) -> None:
    with pytest.raises(ValueError, match="kind"):
        read_stamp(repo, "gate")
    with pytest.raises(ValueError, match="kind"):
        describe_stamp(repo, "gate")


@pytest.mark.parametrize("mode", ["partial", "accept", "return", "review", ""])
def test_write_stamp_refuses_a_mode_that_is_neither_verify_nor_check(repo: Path, mode: str) -> None:
    with pytest.raises(ValueError, match="mode"):
        write_stamp(repo, mode)

    assert not any((repo / name).exists() for name in (STAMP, CHECK_STAMP, REVIEW_STAMP))


def test_a_known_current_tree_gives_the_same_stamp_as_none(repo: Path) -> None:
    write_stamp(repo, "check")
    assert read_stamp(repo, "check", tree_hash(repo)) == read_stamp(repo, "check")

    (repo / "job.py").write_text("x = 8\n")
    assert read_stamp(repo, "check", tree_hash(repo)) == read_stamp(repo, "check")


def test_the_given_tree_is_used_instead_of_a_computed_one(repo: Path) -> None:
    write_stamp(repo, "check")
    stamp = read_stamp(repo, "check")
    assert stamp is not None
    (repo / "job.py").write_text("x = 8\n")
    edited = tree_hash(repo)
    (repo / "job.py").write_text("x = 1\n")

    assert read_stamp(repo, "check") == stamp
    given = read_stamp(repo, "check", edited)
    assert given is not None and not given.fresh
    assert code_changes_since(repo, stamp) == []
    assert code_changes_since(repo, stamp, edited) == ["job.py"]


def test_only_a_return_verdict_is_not_accepted() -> None:
    assert set(VERDICTS.values()) - set(ACCEPTED) == {"return"}
    assert set(ACCEPTED) <= set(VERDICTS.values())


@pytest.mark.parametrize(
    ("verdict_line", "mode"),
    [
        ("Вердикт: принять", "accept"),
        (f"**Вердикт:** {WITH_NOTES} (2 средних)", "accept-with-notes"),
        ("Вердикт: вернуть", "return"),
        ("## ВЕРДИКТ:  Принять", "accept"),
        (f"> _Вердикт_: {WIDE_NOTES}", "accept-with-notes"),
        ("`Вердикт: вернуть`", "return"),
    ],
)
def test_record_review_writes_the_verdict_for_the_reported_tree(
    repo: Path, verdict_line: str, mode: str
) -> None:
    tree = tree_hash(repo)

    message = record_review(
        repo,
        lines(verdict_line, "Предмет: код", "Проверено и чисто: make test", f"Дерево: {tree}"),
    )

    stamp = read_stamp(repo, "review")
    assert stamp is not None
    assert (stamp.mode, stamp.tree, stamp.fresh) == (mode, tree, True)
    assert mode in message and tree in message


@pytest.mark.parametrize(
    "line", ["Вердикт принять", "Итог. Вердикт: принять", "| Вердикт: принять |", "Verdict: accept"]
)
def test_record_review_ignores_a_line_that_is_not_a_verdict(repo: Path, line: str) -> None:
    tree = tree_hash(repo)

    message = record_review(repo, lines(line, "Предмет: код", f"Дерево: {tree}"))

    assert message.startswith("nothing recorded")
    assert not (repo / REVIEW_STAMP).exists()


@pytest.mark.parametrize(
    "line",
    [
        f"Вердикт: принять | {WITH_NOTES} | вернуть",
        "Вердикт: принять | вернуть",
        "Вердикт:",
        "Вердикт: возможно, принять",
        "Вердикт: вернуться",
    ],
)
def test_record_review_revokes_on_a_garbled_verdict_line(repo: Path, line: str) -> None:
    tree = tree_hash(repo)
    record_review(repo, reviewer_report("принять", tree))

    message = record_review(repo, lines(line, "Предмет: код", f"Дерево: {tree}"))

    assert_revoked(repo, message)


def test_record_review_revokes_on_two_different_verdicts(repo: Path) -> None:
    tree = tree_hash(repo)
    record_review(repo, reviewer_report("принять", tree))

    message = record_review(
        repo,
        lines("> Вердикт: принять", "Вердикт: вернуть", "Предмет: код", f"Дерево: {tree}"),
    )

    assert_revoked(repo, message)


def test_record_review_takes_repeated_identical_lines_as_one(repo: Path) -> None:
    tree = tree_hash(repo)

    record_review(
        repo,
        lines(
            "Вердикт: принять",
            "Предмет: код",
            f"Дерево: {tree}",
            "итог",
            "Вердикт: принять",
            f"Дерево: {tree}",
        ),
    )

    stamp = read_stamp(repo, "review")
    assert stamp is not None and stamp.mode == "accept" and stamp.fresh


def test_record_review_revokes_on_two_different_trees(repo: Path) -> None:
    tree = tree_hash(repo)

    message = record_review(
        repo, lines("Вердикт: принять", "Предмет: код", f"Дерево: {tree}", f"Дерево: {'0' * 40}")
    )

    assert_revoked(repo, message)


@pytest.mark.parametrize("subject", ["план", "документ", "**Предмет:** план"])
@pytest.mark.parametrize("verdict", ["принять", "вернуть"])
def test_a_review_of_a_plan_or_a_document_leaves_the_stamp(
    repo: Path, subject: str, verdict: str
) -> None:
    tree = tree_hash(repo)
    record_review(repo, reviewer_report("принять", tree))
    before = (repo / REVIEW_STAMP).read_text()
    line = subject if subject.startswith("*") else f"Предмет: {subject}"

    message = record_review(repo, lines(f"Вердикт: {verdict}", line, f"Дерево: {tree}"))

    assert message.startswith("nothing recorded: not a review of code")
    assert (repo / REVIEW_STAMP).read_text() == before


@pytest.mark.parametrize(
    "subject_lines",
    [(), ("Предмет: код | план | документ",), ("Предмет: код", "Предмет: план"), ("Предмет: всё",)],
)
def test_a_review_without_one_clear_subject_revokes_the_stamp(
    repo: Path, subject_lines: tuple[str, ...]
) -> None:
    tree = tree_hash(repo)
    record_review(repo, reviewer_report("принять", tree))

    message = record_review(repo, lines("Вердикт: принять", *subject_lines, f"Дерево: {tree}"))

    assert_revoked(repo, message)


def test_a_return_on_older_code_is_stamped_for_the_working_tree(repo: Path) -> None:
    tree = tree_hash(repo)
    (repo / "job.py").write_text("x = 2\n")

    message = record_review(repo, reviewer_report("вернуть", tree))

    stamp = read_stamp(repo, "review")
    assert stamp is not None and (stamp.mode, stamp.tree) == ("return", tree_hash(repo))
    assert message.startswith("review stamp: return")


@pytest.mark.parametrize("report", ["", "\n\n", "Report handed back.", "\x00\x01 not a report"])
def test_record_review_of_a_report_without_a_verdict_keeps_the_previous_stamp(
    repo: Path, report: str
) -> None:
    record_review(repo, reviewer_report("принять", tree_hash(repo)))
    before = (repo / REVIEW_STAMP).read_text()

    assert record_review(repo, report).startswith("nothing recorded")
    assert (repo / REVIEW_STAMP).read_text() == before


@pytest.mark.parametrize("verdict", ["вернуть", "принять"])
def test_record_review_without_a_tree_line_revokes_the_previous_stamp(
    repo: Path, verdict: str
) -> None:
    record_review(repo, reviewer_report("принять", tree_hash(repo)))

    message = record_review(
        repo, lines(f"Вердикт: {verdict}", "Предмет: код", "Проверено и чисто: ничего")
    )

    assert_revoked(repo, message)


@pytest.mark.parametrize("wrong", ["short", "long", "ten"])
def test_record_review_revokes_on_a_tree_id_of_the_wrong_length(repo: Path, wrong: str) -> None:
    tree = tree_hash(repo)
    shown = {"short": tree[:39], "long": tree + "a", "ten": tree[:10]}[wrong]

    message = record_review(repo, lines("Вердикт: принять", "Предмет: код", f"Дерево: {shown}"))

    assert_revoked(repo, message)


def test_record_review_refuses_code_changed_after_the_reviewed_tree(repo: Path) -> None:
    tree = tree_hash(repo)
    (repo / "job.py").write_text("x = 2\n")

    message = record_review(repo, reviewer_report("принять", tree))

    assert message.startswith("nothing recorded") and "job.py" in message
    assert not (repo / REVIEW_STAMP).exists()


def test_record_review_accepts_docs_changed_after_the_reviewed_tree(repo: Path) -> None:
    tree = tree_hash(repo)
    (repo / "NOTES.md").write_text("x")
    (repo / "docs").mkdir()
    (repo / "docs" / "plan.txt").write_text("y")

    message = record_review(repo, reviewer_report("принять", tree))

    stamp = read_stamp(repo, "review")
    assert stamp is not None and (stamp.mode, stamp.tree) == ("accept", tree)
    assert not stamp.fresh and code_changes_since(repo, stamp) == []
    assert message.startswith("review stamp")

    (repo / "job.py").write_text("x = 3\n")
    assert code_changes_since(repo, stamp) == ["job.py"]


@pytest.mark.parametrize("unknown", ["0" * 40, "f" * 64])
def test_record_review_revokes_on_an_unknown_tree_without_raising(repo: Path, unknown: str) -> None:
    message = record_review(repo, reviewer_report("принять", unknown))

    assert_revoked(repo, message)


def test_record_review_revokes_on_an_object_that_is_not_a_tree(repo: Path) -> None:
    commit = git_out(repo, "rev-parse", "HEAD")

    message = record_review(repo, reviewer_report("принять", commit))

    assert_revoked(repo, message)


@pytest.mark.parametrize(
    "form", ["Дерево: {}", "**Дерево:** {}", "- дерево: `{}`", "> ДЕРЕВО: {} (до правок)"]
)
def test_record_review_reads_the_tree_line_in_the_same_markup_as_the_verdict(
    repo: Path, form: str
) -> None:
    tree = tree_hash(repo)

    record_review(repo, lines("Вердикт: принять", "- **Предмет:** код", form.format(tree)))

    stamp = read_stamp(repo, "review")
    assert stamp is not None and stamp.tree == tree and stamp.fresh


def test_record_review_reads_the_tree_id_in_any_case(repo: Path) -> None:
    tree = tree_hash(repo)

    record_review(repo, lines("Вердикт: принять", "ПРЕДМЕТ: Код", f"Дерево: {tree.upper()}"))

    stamp = read_stamp(repo, "review")
    assert stamp is not None and stamp.tree == tree and stamp.fresh


def test_record_review_reads_a_sha256_tree_id(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "--object-format=sha256")
    git(tmp_path, "config", "user.email", "t@example.invalid")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text(f"{REVIEW_STAMP}\n")
    (tmp_path / "job.py").write_text("x = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    tree = tree_hash(tmp_path)
    assert len(tree) == 64

    record_review(tmp_path, reviewer_report("принять", tree))

    stamp = read_stamp(tmp_path, "review")
    assert stamp is not None and stamp.tree == tree and stamp.fresh


def test_record_review_twice_with_one_report_changes_only_the_time(repo: Path) -> None:
    report = reviewer_report(WITH_NOTES, tree_hash(repo))
    record_review(repo, report)
    first = read_stamp(repo, "review")
    record_review(repo, report)
    second = read_stamp(repo, "review")

    assert first is not None and second is not None
    assert (
        (first.mode, first.tree) == (second.mode, second.tree) == ("accept-with-notes", first.tree)
    )


def test_a_later_review_of_the_same_tree_replaces_the_earlier_one(repo: Path) -> None:
    tree = tree_hash(repo)
    record_review(repo, reviewer_report("вернуть", tree))
    record_review(repo, reviewer_report("принять", tree))

    stamp = read_stamp(repo, "review")
    assert stamp is not None and stamp.mode == "accept"


def test_cli_prints_the_tree_id(repo: Path) -> None:
    result = cli("tree", repo)

    assert result.returncode == 0
    assert result.stdout.strip() == tree_hash(repo) == git_out(repo, "rev-parse", "HEAD^{tree}")


def test_cli_writes_a_check_stamp(repo: Path) -> None:
    assert cli("stamp", "check", repo).returncode == 0

    stamp = read_stamp(repo, "check")
    assert stamp is not None and stamp.mode == "check" and stamp.fresh
    assert read_stamp(repo) is None


def test_cli_shows_each_kind_of_stamp(repo: Path) -> None:
    write_stamp(repo, "check")
    assert cli("show", "check", repo).stdout.startswith("check at ")
    assert cli("show", "review", repo).stdout.strip() == "none"
    assert cli("show", "verify", repo).stdout.strip() == "none"
    assert cli("show", repo).stdout.strip() == "none"

    write_stamp(repo, "full")
    assert cli("show", repo).stdout.startswith("full at ")
    record_review(repo, reviewer_report("принять", tree_hash(repo)))
    assert cli("show", "review", repo).stdout.startswith("accept at ")


@pytest.mark.parametrize(
    "args", [("show", "gate"), ("stamp", "review"), ("stamp", "accept"), ("stamp", "partial")]
)
def test_cli_refuses_an_unknown_kind_or_mode(repo: Path, args: tuple[str, ...]) -> None:
    result = cli(*args, repo)

    assert result.returncode != 0
    assert not (repo / REVIEW_STAMP).exists() and not (repo / STAMP).exists()


def test_cli_refuses_a_command_without_a_root() -> None:
    assert cli("tree").returncode != 0


def test_make_check_runs_lint_and_test_through_run_check() -> None:
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", "-C", str(REPO), "check"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.split() == ["python3", "scripts/agent_state.py", "check", f'"{REPO}"']
    assert CHECK_COMMAND == ("make", "--no-print-directory", "lint", "test")


def test_run_check_stamps_the_tree_the_checks_passed_on(repo: Path) -> None:
    tree = tree_hash(repo)

    assert run_check(repo, ("true",)) == 0

    stamp = read_stamp(repo, "check")
    assert stamp is not None and (stamp.mode, stamp.tree, stamp.fresh) == ("check", tree, True)


def test_run_check_writes_no_stamp_when_a_check_fails(repo: Path) -> None:
    assert run_check(repo, ("false",)) != 0
    assert not (repo / CHECK_STAMP).exists()


def test_run_check_writes_no_stamp_for_a_tree_edited_while_it_ran(repo: Path) -> None:
    write_stamp(repo, "check")
    before = (repo / CHECK_STAMP).read_text()

    assert run_check(repo, ("sh", "-c", "echo 'x = 9' > job.py")) != 0
    assert (repo / CHECK_STAMP).read_text() == before


def test_run_check_drops_the_make_and_pytest_option_variables(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("MAKEFLAGS", "MFLAGS", "GNUMAKEFLAGS", "PYTEST_ADDOPTS"):
        monkeypatch.setenv(name, "-i --collect-only")

    probe = 'test -z "$MAKEFLAGS$MFLAGS$GNUMAKEFLAGS$PYTEST_ADDOPTS"'
    assert run_check(repo, ("sh", "-c", probe)) == 0


def test_cli_check_without_lint_and_test_targets_writes_no_stamp(repo: Path) -> None:
    result = cli("check", repo)

    assert result.returncode != 0
    assert not (repo / CHECK_STAMP).exists()


def test_every_stamp_is_git_ignored_in_this_repo() -> None:
    ignored = (REPO / ".gitignore").read_text().split()

    assert {STAMP, CHECK_STAMP, REVIEW_STAMP} <= set(ignored)
