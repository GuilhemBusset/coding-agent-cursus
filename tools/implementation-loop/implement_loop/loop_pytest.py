"""pytest plugin of the trusted verifier: every pytest process a check command starts records
what it selected and how each test ended.

The verifier loads it with `-p implement_loop.loop_pytest` through PYTEST_ADDOPTS, with the
engine's own `tools/implementation-loop` on PYTHONPATH, so it reaches pytest however the
command starts it (`pytest A && pytest B`, `bash run.sh`, `uv run pytest`, `make test`).
Each pytest session writes `<LOOP_REPORT_DIR>/run-<pid>-<time_ns>.json`:

    {"cwd", "rootdir", "exitstatus", "cases": [{"id", "outcome"}], "collected": [ids]}

`outcome` is passed, failed, skipped, error (setup or teardown failed, or a file failed to
collect), xfailed or xpassed. Ids are relative to LOOP_REPO_ROOT, whatever pytest's rootdir
is: `sessions/01-fundamentals/tests/test_x.py::TestA::test_b[1]`. `collected` is what the
session selected, after `-k`/`-m` deselection.

Without both LOOP_REPORT_DIR and LOOP_REPO_ROOT it does nothing. Nor does it in a pytest
started by a test of another recording pytest (a test of a test runner, an xdist worker): that
run's tests are fixtures of the outer test, not the check's. It runs inside whatever Python the
command uses, so it keeps to the standard library and to Python 3.8 syntax.
"""

from __future__ import annotations

import atexit
import json
import os
import sys
import time

import pytest

REPORT_DIR = os.environ.get("LOOP_REPORT_DIR") or ""
REPO_ROOT = os.environ.get("LOOP_REPO_ROOT") or ""
OWNER = "LOOP_PYTEST_PID"   # the recording pytest process; its child processes inherit it
NESTED = os.environ.get(OWNER, str(os.getpid())) != str(os.getpid())
ACTIVE = bool(REPORT_DIR and REPO_ROOT) and not NESTED
if ACTIVE:
    os.environ[OWNER] = str(os.getpid())

# a later outcome of the same test only ever makes it worse
SEVERITY = {"passed": 0, "xfailed": 1, "skipped": 2, "xpassed": 3, "failed": 4, "error": 5}

_written = []   # records this process wrote, for the exit fallback


def _write(record: dict) -> bool:
    try:
        os.makedirs(REPORT_DIR, exist_ok=True)
        name = f"run-{os.getpid()}-{time.time_ns()}.json"
        tmp = os.path.join(REPORT_DIR, f".{name}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f)
        os.replace(tmp, os.path.join(REPORT_DIR, name))
    except OSError as e:
        sys.stderr.write(f"implement-loop: cannot write the pytest result record: {e}\n")
        return False
    _written.append(name)
    return True


def _at_exit() -> None:
    """pytest ended before any session could record itself (a bad option, a broken plugin):
    leave a record anyway, so the verifier knows pytest ran and did not finish."""
    if not _written:
        _write({"cwd": os.getcwd(), "rootdir": None, "exitstatus": None, "cases": [], "collected": []})


def _forget_engine_package() -> None:
    """Loading this plugin imported the engine's `implement_loop` package. Drop it from the
    module cache, so tests of a worktree's own `implement_loop` import that copy, not this one."""
    here = os.path.dirname(os.path.realpath(__file__))
    for name in [n for n in sys.modules if n == "implement_loop" or n.startswith("implement_loop.")]:
        path = getattr(sys.modules[name], "__file__", None) or ""
        if path and os.path.dirname(os.path.realpath(path)) == here:
            del sys.modules[name]


class Recorder:
    """One per pytest session (a process can call `pytest.main` more than once)."""

    def __init__(self, config) -> None:
        self.config = config
        rootdir = getattr(config, "rootpath", None) or getattr(config, "rootdir", None) or os.getcwd()
        self.rootdir = os.path.realpath(str(rootdir))
        self.repo_root = os.path.realpath(REPO_ROOT)
        self.ids: dict[str, str] = {}
        self.outcomes: dict[str, str] = {}
        self.collected: list[str] = []

    def repo_id(self, nodeid: str, path=None) -> str:
        """`nodeid` with its file part made relative to the repository root."""
        if nodeid in self.ids:
            return self.ids[nodeid]
        file_part, sep, rest = nodeid.partition("::")
        full = os.path.realpath(str(path) if path is not None else os.path.join(self.rootdir, file_part))
        rel = os.path.relpath(full, self.repo_root)
        if rel == os.pardir or rel.startswith(os.pardir + os.sep):
            rel = full   # outside the repository: keep it absolute rather than guess
        rel = rel.replace(os.sep, "/")
        if rel == ".":
            rel = ""
        return rel + sep + rest

    def note(self, nodeid: str, outcome: str) -> None:
        key = self.repo_id(nodeid)
        if key not in self.outcomes or SEVERITY[outcome] > SEVERITY[self.outcomes[key]]:
            self.outcomes[key] = outcome

    def pytest_collection_finish(self, session) -> None:
        self.collected = []
        for item in session.items:
            path = getattr(item, "path", None) or getattr(item, "fspath", None)
            self.ids[item.nodeid] = self.repo_id(item.nodeid, path)
            self.collected.append(self.ids[item.nodeid])

    def pytest_collectreport(self, report) -> None:
        if report.failed:
            self.note(report.nodeid, "error")
        elif report.skipped:
            self.note(report.nodeid, "skipped")

    def pytest_runtest_logreport(self, report) -> None:
        xfail = hasattr(report, "wasxfail")
        if report.when == "call":
            if report.passed:
                self.note(report.nodeid, "xpassed" if xfail else "passed")
            elif report.failed:
                self.note(report.nodeid, "failed")
            elif report.skipped:
                self.note(report.nodeid, "xfailed" if xfail else "skipped")
        elif report.failed:   # setup or teardown
            self.note(report.nodeid, "error")
        elif report.skipped:  # skipped in setup: skip marks, skipif, xfail(run=False)
            self.note(report.nodeid, "xfailed" if xfail else "skipped")

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus) -> None:
        status = getattr(session, "exitstatus", exitstatus)
        record = {"cwd": os.getcwd(), "rootdir": self.rootdir, "exitstatus": int(status),
                  "cases": [{"id": k, "outcome": v} for k, v in self.outcomes.items()],
                  "collected": self.collected}
        if not _write(record):
            session.exitstatus = 3   # no record means no evidence: fail rather than pass unaccounted


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config) -> None:
    if ACTIVE:
        _forget_engine_package()


def pytest_configure(config) -> None:
    if ACTIVE and not config.pluginmanager.has_plugin("implement-loop-recorder"):
        config.pluginmanager.register(Recorder(config), "implement-loop-recorder")


if ACTIVE:
    atexit.register(_at_exit)
