# Student setup verification record

Evidence behind the one-command student setup ([README.md](README.md): `install.sh`,
`install.ps1`, `prepare.py`), modeled on Session 1's
[pre-work verification record](../../sessions/01-fundamentals/prework-verification.md). The
student docs show the same status for each track; `tests/student_setup/test_static.py` fails
when the two disagree.

## Track status

Two kinds of evidence count, and each track lists both:

- **CI (non-interactive):** "tested in CI" means `.github/workflows/student-setup.yml` runs the
  setup for real on that track with `--yes --agent both --no-login`, twice, on every pull request
  that changes the student setup and nightly, and `tests/student_setup/ci_verify.py` checks that
  git, gh, uv, mise, `claude` and `codex` run at or above the floors, that `core.hooksPath` is
  `.githooks`, that `mise exec -- uv sync --locked` exits 0 in every session, that the second run
  installed nothing, and that the clone's `git status --porcelain` and HEAD did not change. CI
  cannot log in, so it never runs the logins or the setup check.
- **Live (interactive, real logins):** "tested live" means a person ran the one-liner on that
  platform, logged in to GitHub and to an agent in the browser, and the setup check passed, with
  the run recorded below. A track without such a run is untested.

| Track | CI (non-interactive) | Live (interactive, real logins) | Evidence |
| --- | --- | --- | --- |
| Windows (PowerShell) | tested in CI | untested | `windows-latest`, through `powershell.exe` (Windows PowerShell 5.1) and `iex`, as `irm ... \| iex` runs it; git and gh are preinstalled there, so winget's installs of Git for Windows and gh (and its UAC prompt) are not exercised. No live run recorded. |
| Windows with WSL 2 | not in CI | untested | CI has no WSL. The WSL detection and its plan are tested offline (`test_install.py`); a non-interactive run on WSL 2 is recorded below. No live run recorded. |
| macOS | tested in CI | untested | `macos-latest` (Apple silicon), with `/bin/bash` 3.2; git (Command Line Tools) and gh are preinstalled there, so the Command Line Tools dialog and the gh archive path are not exercised. Intel Macs are not in CI. No live run recorded. |
| Debian / Ubuntu | tested in CI | untested | Clean `ubuntu:26.04` and `debian:13.7` containers: git and gh from apt and GitHub's apt repository. No live run recorded. |
| Fedora | tested in CI | untested | A clean `fedora:45` container: git from dnf, gh from GitHub's rpm repository. No live run recorded. |
| Arch | tested in CI | untested | A clean `archlinux:base-20261101.0.620205` container: git and github-cli from pacman. No live run recorded. |
| Other Linux | not in CI | untested | The detection and the stop at the system tools step are tested offline (`test_install.py`). No live run recorded. |

The offline tests (`tests/student_setup`, in CI's student-setup job) cover every track's
`--dry-run` plan through simulated detection, a rerun in a clone on a feature branch with staged,
unstaged and untracked changes, session discovery, the piped one-liner, the floors, and the
Bash 3.2 and PowerShell 5.1 syntax.

## How to record a live run

On the platform itself (one each for macOS, native Windows and a native Linux distribution is
the owner's part of issue #150), with a GitHub account and a Claude or ChatGPT plan:

1. Run the track's one-liner from [README.md](README.md#the-command-for-your-platform) in a new
   terminal, answer its questions, and log in when the browser opens.
2. It ends with the setup check's summary block. The run counts only if that block says
   `result: PASS`.
3. Add a section below with the date, the track, the OS version (`sw_vers`, `uname -a`, or
   `winver` on Windows), the agent(s) chosen, the full output of the run (from the plan to the
   next steps), the summary block, and `sha256sum` (or `Get-FileHash` on Windows) of
   `setup/student/install.sh` or `install.ps1` and `prepare.py` at the commit you ran.
4. Change that track's "Live" cell above to `tested live`, and the same status line in
   [README.md](README.md#tracks), in one pull request.

## Non-interactive run on WSL 2

On 2026-11-04 the implementation loop's builder ran `bash tests/student_setup/run_local.sh` on
its own host, WSL 2 with Ubuntu 24.04.4 LTS, x86_64. That script runs `run_twice.sh` (what the
macOS and Linux CI jobs run) in an empty `HOME`, with only the system's folders on `PATH` (git
2.43.0 and gh 2.45.0 there), against a snapshot of this branch's working tree. Both runs and
`ci_verify.py` passed. The first run's tool lines were:

```text
[setup] git: present 2.43.0 (>= 2.23.0), left alone
[setup] gh: present 2.45.0 (>= 2.0.0), left alone
[setup] uv: installed 0.13.7
[setup] mise: installed 2026.10.12
[setup] claude: installed 2.1.318
[setup] codex: installed 0.166.0
[setup] PATH: the official installers changed ~/.profile ~/.zshrc; open a new terminal to pick that up.
```

It then cloned the course, activated the hooks and synced `sessions/01-fundamentals`. The whole
first run printed 32 lines. The second run reported all six tools present and left alone and
installed nothing, and `ci_verify.py` found every tool at or above its floor, `core.hooksPath`
set to `.githooks`, and `mise exec -- uv sync --locked` exiting 0. This is not a live run: no
person ran it, nothing was logged in, and the setup check did not run (`--no-login`).

## Live runs

None recorded yet.
