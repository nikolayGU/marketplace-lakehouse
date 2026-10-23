"""FAIL_ON_SKIP=1 (make test-spark) turns every skip into a failure: `-p no:skipping` stops only
the skip and skipif markers, not `pytest.skip()`, a skip in a fixture or `importorskip`."""

import os
from collections.abc import Generator

import pytest

FAIL_ON_SKIP = os.environ.get("FAIL_ON_SKIP") == "1"


def _fail(report: pytest.TestReport | pytest.CollectReport) -> None:
    if FAIL_ON_SKIP and report.skipped and not hasattr(report, "wasxfail"):
        report.outcome = "failed"
        report.longrepr = f"skipped while FAIL_ON_SKIP=1: {report.longrepr}"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport() -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    _fail(report)
    return report


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report() -> Generator[None, pytest.CollectReport, pytest.CollectReport]:
    report = yield
    _fail(report)
    return report
