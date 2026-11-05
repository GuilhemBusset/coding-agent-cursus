"""A9's agent part: the interactive path a live run takes, and the record a live run lands in.

The live runs themselves (real browser logins on macOS, native Windows and a native Linux) are the
owner's. What agents deliver is proven here: install.sh asks on the terminal, logs in to GitHub and
to each agent there, and runs the setup check; and no track is labeled tested live without a
recorded run.
"""

from __future__ import annotations

import fcntl
import os
import re
import select
import subprocess
import termios
import time

from student_sandbox import STUDENT, Box, course, git
from test_static import statuses_in_docs, statuses_in_record

DEBIAN = 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\nVERSION_ID="13"\n'
# A tool not logged in yet: its status command fails, its login logs whether it got a terminal.
LOGGED_OUT = """#!/bin/sh
if [ -t 0 ]; then t=tty; else t=notty; fi
echo "{name} $* <$t" >> "$STUB_LOG"
case "$1 $2" in
  "--version "*) echo "{version}" ;;
  "auth status"|"login status") exit 1 ;;
esac
exit 0
"""
VERSIONS = {"gh": "gh version 2.65.1 (2025-01-06)", "claude": "2.1.7 (Claude Code)", "codex": "codex-cli 0.98.3"}
ANSWERS = [("Which agent do you use?", "3"), ("Go ahead? [Y/n]", ""),
           ("Your name, for your git commits:", "Ada Student"), ("Your email, for your git commits:", "ada@example.com")]


def on_a_terminal(argv: list[str], env: dict[str, str], cwd) -> tuple[int, str, list[str]]:
    """Runs argv with a pseudo-terminal as its controlling terminal (so /dev/tty opens), answering
    each prompt in ANSWERS as it appears. Returns the exit code, the output, and the prompts seen."""
    master, slave = os.openpty()

    def controlling_tty() -> None:
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, env=env, cwd=cwd,
                            preexec_fn=controlling_tty, close_fds=True)
    os.close(slave)
    out, asked, deadline = "", [], time.monotonic() + 120
    while time.monotonic() < deadline:
        ready, _, _ = select.select([master], [], [], 0.5)
        if ready:
            try:
                chunk = os.read(master, 4096).decode(errors="replace")
            except OSError:  # the child closed the terminal
                break
            if not chunk:
                break
            out += chunk
            for prompt, answer in ANSWERS:
                if out.count(prompt) > asked.count(prompt):
                    asked.append(prompt)
                    os.write(master, (answer + "\n").encode())
        elif proc.poll() is not None:
            break
    os.close(master)
    code = proc.wait(timeout=30)
    return code, out.replace("\r\n", "\n"), asked


def test_an_interactive_run_asks_on_the_terminal_logs_in_and_runs_the_check(tmp_path):
    box = Box(tmp_path)
    box.real("git")
    for name in ("curl", "sudo", "apt-get"):
        box.stub(name)
    box.stub("uv")
    box.stub("mise")
    for name, version in VERSIONS.items():
        box.stub(name, LOGGED_OUT.replace("{name}", name).replace("{version}", version))
    box.os_release(DEBIAN)
    repo = course(tmp_path, {"01-alpha": ("mise.toml", "pyproject.toml", "uv.lock")})
    check = repo / "sessions/01-alpha/exercises/check_setup.py"
    check.parent.mkdir()
    check.write_text("print('=== setup check summary ===')\nprint('result: PASS')\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "check")

    # No flags at all: what a student types.
    code, out, asked = on_a_terminal(["bash", str(repo / "setup/student/install.sh")], box.env, box.root)
    assert code == 0, out
    assert asked == [prompt for prompt, _ in ANSWERS], (asked, out)
    home_git = ["git", "config", "--global", "--get"]
    for key, value in (("user.name", "Ada Student"), ("user.email", "ada@example.com")):
        got = subprocess.run([*home_git, key], env=box.env, capture_output=True, text=True).stdout.strip()
        assert got == value, key
    calls = box.calls()
    for login in ("gh auth login --hostname github.com --git-protocol https --web <tty",
                  "claude auth login <tty", "codex login <tty"):
        assert login in calls, (login, calls)
    assert "gh auth setup-git --hostname github.com <notty" in calls
    order = [i for i, c in enumerate(calls) if c.split(" <")[0] in
             ("gh auth login --hostname github.com --git-protocol https --web", "claude auth login", "codex login")]
    assert order == sorted(order) and calls[order[0]].startswith("gh "), "GitHub first, then the agents"
    assert "logins: skipped" not in out and "setup check: skipped" not in out
    assert "result: PASS" in out and "Next steps:" in out, out


def live_runs_recorded() -> str:
    record = (STUDENT / "verification.md").read_text(encoding="utf-8")
    return record.split("\n## Live runs", 1)[1]


def test_no_track_is_labeled_tested_live_without_a_recorded_run():
    record, docs = statuses_in_record(), statuses_in_docs()
    runs = live_runs_recorded()
    headings = re.findall(r"^### (.+)$", runs, re.M)
    for track, (_, live) in record.items():
        if live == "tested live":
            assert any(track in h for h in headings), f"{track} is tested live with no run under 'Live runs'"
        else:
            assert live == "untested" and docs[track][1] == "untested", track
    # The owner's three runs have a procedure to follow and a place to land.
    procedure = (STUDENT / "verification.md").read_text(encoding="utf-8").split("## How to record a live run", 1)
    assert len(procedure) == 2 and "result: PASS" in procedure[1].split("\n## ", 1)[0]
