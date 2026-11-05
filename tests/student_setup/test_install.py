"""install.sh and install.ps1 end to end, against stub tools: each track's dry run, a rerun in
an existing clone, and the piped one-liner cloning the course."""

from __future__ import annotations

import re
import shutil

import pytest
from student_sandbox import STUDENT, Box, course, git, powershell, tree

PINS = dict(line.split("=", 1) for line in (STUDENT / "versions.env").read_text().splitlines()
            if line and not line.startswith("#"))
DEBIAN = 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\nVERSION_ID="13"\n'
UBUNTU = 'PRETTY_NAME="Ubuntu 26.04 LTS"\nID=ubuntu\nID_LIKE=debian\nVERSION_ID="26.04"\n'
FEDORA = 'PRETTY_NAME="Fedora Linux 45 (Container Image)"\nID=fedora\nVERSION_ID=45\n'
ARCH = 'PRETTY_NAME="Arch Linux"\nID=arch\n'
OTHER = 'PRETTY_NAME="openSUSE Tumbleweed"\nID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n'
# Only these calls are allowed in a dry run: reading versions and the platform.
READ_ONLY = re.compile(r"^(\S+ --version(?: @.*)?|uname -[sm]|xcode-select -p|sw_vers -productVersion)$")

TRACKS = {
    "macos-homebrew": ("Darwin", None, False, True,
                       ["macOS track", "Homebrew (brew install gh)", "xcode-select --install opens a dialog"]),
    "macos-no-homebrew": ("Darwin", None, False, False,
                          ["macOS track", f"gh_{PINS['GH_VERSION']}_macOS_arm64.zip (SHA-256 checked)"]),
    "debian": ("Linux", DEBIAN, False, False,
               ["Debian / Ubuntu track (Debian GNU/Linux 13", "These commands use sudo", "sudo apt-get update",
                "GitHub's apt repository", "sudo apt-get install -y gh"]),
    "ubuntu": ("Linux", UBUNTU, False, False, ["Debian / Ubuntu track (Ubuntu 26.04 LTS", "sudo apt-get install -y gh"]),
    "fedora": ("Linux", FEDORA, False, False,
               ["Fedora track", "sudo dnf config-manager addrepo --from-repofile=https://cli.github.com/packages/rpm/gh-cli.repo",
                "sudo dnf install -y gh"]),
    "arch": ("Linux", ARCH, False, False,
             ["Arch track", "sudo pacman -Sy --noconfirm", "sudo pacman -S --needed --noconfirm github-cli"]),
    "other-linux": ("Linux", OTHER, False, False,
                    ["other Linux track (openSUSE Tumbleweed", "cannot install git, gh or curl on this distribution"]),
    "wsl": ("Linux", UBUNTU, True, False,
            ["Windows with WSL 2, Debian / Ubuntu track", "Warning: /mnt/c/Users/student/cursus is on the Windows drive",
             "sudo apt-get install -y gh"]),
}


def unpacked_script(box: Box):
    """install.sh and versions.env alone, as the one-liner has them: no clone around them."""
    folder = box.root / "script"
    folder.mkdir()
    for name in ("install.sh", "versions.env"):
        shutil.copy2(STUDENT / name, folder / name)
    return folder / "install.sh"


@pytest.mark.parametrize("track", TRACKS)
def test_dry_run_prints_each_tracks_plan_and_writes_nothing(tmp_path, track):
    os_name, release, wsl, brew, expected = TRACKS[track]
    box = Box(tmp_path)
    for name in ("curl", "wget", "sudo", "apt-get", "dnf", "pacman", "dpkg", "sw_vers"):
        box.stub(name)
    box.stub("git")
    box.stub("mise", version="2023.12.0")  # below the floor
    box.stub("xcode-select", "#!/bin/sh\necho \"xcode-select $*\" >> \"$STUB_LOG\"\nexit 2\n")
    if brew:
        box.stub("brew")
    if release:
        box.os_release(release, wsl=wsl)
    script = unpacked_script(box)
    before = tree(tmp_path, skip=("calls.log",))
    result = box.run(["bash", str(script), "--dry-run", "--dir", "/mnt/c/Users/student/cursus"],
                     FAKE_OS=os_name, FAKE_ARCH="arm64" if os_name == "Darwin" else "x86_64")
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    for text in [*expected, f"uv {PINS['UV_VERSION']} from https://astral.sh/uv/{PINS['UV_VERSION']}/install.sh",
                 f"present 2023.12.0, below the floor {PINS['MISE_FLOOR']}", "claude   missing", "codex    missing",
                 "Dry run: nothing was installed, written or changed."]:
        assert text in out, f"{track}: {text!r} not in\n{out}"
    if not wsl:
        assert "Windows drive" not in out
    assert tree(tmp_path, skip=("calls.log",)) == before, "a dry run wrote something"
    assert [c for c in box.calls() if not READ_ONLY.match(c)] == [], "a dry run called more than --version"


def test_windows_dry_run_prints_its_plan_and_writes_nothing(tmp_path):
    box = Box(tmp_path)
    box.stub("winget")
    box.stub("gh")
    box.stub("uv", version="uv 0.4.9")  # below the floor
    # The PowerShell host caches its startup data there; install.ps1 writes nothing.
    skip = ("calls.log", "host-cache")
    before = tree(tmp_path, skip=skip)
    result = box.run([powershell(), "-NoProfile", "-File", str(STUDENT / "install.ps1"), "-DryRun"],
                     OS="Windows_NT", USERPROFILE=str(box.home), PROCESSOR_ARCHITECTURE="AMD64",
                     XDG_CACHE_HOME=str(box.root / "host-cache"))
    assert result.returncode == 0, result.stdout + result.stderr
    for text in ["Windows (PowerShell) track", "git      missing: install Git for Windows", "--scope user",
                 "administrator approval (UAC)", f"https://astral.sh/uv/{PINS['UV_VERSION']}/install.ps1",
                 "present 0.4.9, below the floor", "https://mise.run/powershell", "https://claude.ai/install.ps1",
                 "Dry run: nothing was installed, written or changed."]:
        assert text in result.stdout, f"{text!r} not in\n{result.stdout}"
    assert tree(tmp_path, skip=skip) == before
    assert [c for c in box.calls() if not READ_ONLY.match(c)] == []


def snapshot(repo):
    return {"branch": git(repo, "symbolic-ref", "HEAD"), "head": git(repo, "rev-parse", "HEAD"),
            "index": git(repo, "ls-files", "-s"), "staged": git(repo, "diff", "--cached"),
            "unstaged": git(repo, "diff"), "status": git(repo, "status", "--porcelain=v1", "-uall"),
            "files": tree(repo, skip=(".git",))}


def stubbed_tools(box: Box) -> None:
    box.real("git")
    for name in ("gh", "claude", "codex", "curl", "sudo", "apt-get"):
        box.stub(name)
    box.stub("uv")
    box.stub("mise")
    box.os_release(DEBIAN)


def test_existing_clone_on_a_feature_branch_is_left_as_it_is(tmp_path):
    box = Box(tmp_path)
    stubbed_tools(box)
    repo = course(tmp_path, {"01-alpha": ("mise.toml", "pyproject.toml", "uv.lock", "notes.md")})
    git(repo, "switch", "-q", "-c", "feat/my-work")
    (repo / "sessions/01-alpha/notes.md").write_text("committed on the branch\n")
    git(repo, "commit", "-q", "-am", "work")
    (repo / "sessions/01-alpha/notes.md").write_text("staged\n")
    git(repo, "add", "sessions/01-alpha/notes.md")
    (repo / "sessions/01-alpha/notes.md").write_text("staged, then edited again\n")
    (repo / "sessions/01-alpha/untracked.txt").write_text("new\n")
    before = snapshot(repo)
    for _ in range(2):
        result = box.run(["bash", str(repo / "setup/student/install.sh"), "--yes", "--agent", "claude", "--no-login"])
        assert result.returncode == 0, result.stdout + result.stderr
        assert snapshot(repo) == before
    out = result.stdout
    assert f"clone: using the clone this script runs from, {repo} (left as it is)" in out
    for tool in ("git", "gh", "uv", "mise", "claude"):
        assert re.search(rf"^\[setup\] {tool}: present \S+.*left alone$", out, re.MULTILINE), tool
    assert not re.search(r"^\[setup\] .*\b(installing|installed)\b", out, re.MULTILINE)
    assert "logins: skipped (--no-login)" in out and "setup check: skipped (--no-login)" in out
    assert "[setup] sessions/01-alpha: synced" in out
    assert git(repo, "config", "--get", "core.hooksPath").strip() == ".githooks"
    assert not [c for c in box.calls() if c.startswith(("sudo", "apt-get", "curl", "gh auth", "claude auth")) and "--version" not in c]


def test_piped_one_liner_clones_the_course_then_a_rerun_reuses_it(tmp_path):
    box = Box(tmp_path)
    stubbed_tools(box)
    box.real("curl")
    source = course(tmp_path, {"01-alpha": ("mise.toml", "pyproject.toml", "uv.lock")})
    script = (source / "setup/student/install.sh").read_text()
    runs = [box.run(["bash", "-s", "--", "--yes", "--agent", "both", "--no-login"], input=script,
                    CURSUS_RAW_BASE=f"file://{source}", CURSUS_CLONE_URL=f"file://{source}") for _ in range(2)]
    for result in runs:
        assert result.returncode == 0, result.stdout + result.stderr
    clone = box.home / "coding-agent-cursus"
    assert f"clone: cloned file://{source} into {clone}" in runs[0].stdout
    assert f"clone: {clone} already exists, left as it is" in runs[1].stdout
    assert git(clone, "rev-parse", "HEAD") == git(source, "rev-parse", "HEAD")
    assert git(clone, "config", "--get", "core.hooksPath").strip() == ".githooks"


def test_without_a_terminal_it_stops_unless_yes_and_no_login(tmp_path):
    box = Box(tmp_path)
    stubbed_tools(box)
    repo = course(tmp_path, {"01-alpha": ("mise.toml", "pyproject.toml", "uv.lock")})
    for args, message in ((["--agent", "codex", "--yes"], "no terminal to ask on"),
                          (["--no-login", "--yes"], "no terminal to ask which agent")):
        result = box.run(["bash", str(repo / "setup/student/install.sh"), *args])
        assert result.returncode == 1 and message in result.stdout, result.stdout
    assert not [c for c in box.calls() if c.startswith("mise ") and "--version" not in c]


def test_windows_run_through_iex_leaves_an_existing_clone_as_it_is(tmp_path):
    box = Box(tmp_path)
    stubbed_tools(box)
    box.stub("winget")
    repo = course(tmp_path, {"01-alpha": ("mise.toml", "pyproject.toml", "uv.lock")})
    git(repo, "switch", "-q", "-c", "feat/windows")
    (repo / "sessions/01-alpha/mise.toml").write_text("edited\n")
    before = snapshot(repo)
    # As `irm ... | iex` runs it: no script path, so the clone comes from CURSUS_DIR.
    command = f"Get-Content -Raw '{repo}/setup/student/install.ps1' | Invoke-Expression; exit $LASTEXITCODE"
    result = box.run([powershell(), "-NoProfile", "-Command", command], OS="Windows_NT", USERPROFILE=str(box.home),
                     XDG_CACHE_HOME=str(box.root / "host-cache"), CURSUS_YES="1", CURSUS_AGENT="both",
                     CURSUS_NO_LOGIN="1", CURSUS_DIR=str(repo), CURSUS_RAW_BASE=str(repo))
    assert result.returncode == 0, result.stdout + result.stderr
    assert snapshot(repo) == before
    for tool in ("git", "gh", "uv", "mise", "claude", "codex"):
        assert re.search(rf"^\[setup\] {tool}: present \S+.*left alone$", result.stdout, re.MULTILINE), tool
    assert f"clone: {repo} already exists, left as it is" in result.stdout
    assert "[setup] sessions/01-alpha: synced" in result.stdout and "setup check: skipped (-NoLogin)" in result.stdout
    assert not [c for c in box.calls() if c.startswith("winget") or " auth " in c]
