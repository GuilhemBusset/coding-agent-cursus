# ADR 0015 — Student setup: one command per platform, bootstrapped from `main`

- **Status:** Accepted
- **Date:** 2026-11-04
- **Deciders:** Guilhem Busset (instructor / repo owner)
- **Context:** [ADR 0001](0001-self-contained-per-session-subfolders.md), [ADR 0002](0002-agent-agnostic-claude-code-and-codex.md), [ADR 0009](0009-homework-on-per-student-branches.md), [ADR 0010](0010-platform-support.md), [ADR 0013](0013-test-tiers-and-selection.md), issue #150

## Context

Until now a student assembled their machine by hand from four places: the per-tool install
commands on Session 1's pre-work page (30 to 45 minutes of copying), a manual clone, Bash-only
`setup/session-01-fundamentals.sh` (Session 1 only), and the setup check. Nothing told them to
activate the git hooks. Only WSL 2 had ever been tested. Students use their own machines, on
Linux, macOS or Windows (ADR 0010), and have Claude Code or Codex, not necessarily both
(ADR 0002).

## Decision

1. **One command per track.** A student copies one line, with no flags:
   - **Windows (PowerShell):** `irm <raw URL>/setup/student/install.ps1 | iex`, written for
     Windows PowerShell 5.1, the version Windows ships. git (Git for Windows, which brings the Git
     Bash Claude Code needs) and gh come from winget, the package manager current Windows ships.
   - **macOS, Linux and WSL:** `curl -fsSL <raw URL>/setup/student/install.sh | bash`, written
     for Bash 3.2, macOS's `/bin/bash`. git and gh come from where each platform's users expect:
     the Xcode Command Line Tools and Homebrew or GitHub's release archive on macOS (Homebrew is
     not required); apt with GitHub's apt repository on Debian and Ubuntu; dnf with GitHub's rpm
     repository on Fedora; pacman on Arch. WSL 2 is the Linux track run inside WSL, because the
     course's Bash tooling and agents run there natively. Any other distribution gets the same
     script, which stops at the system tools step and points to the manual commands.

   These tracks cover the platforms students bring and that both agents' official installers
   support. A native `install.ps1` is a deliberate exception to ADR 0010's "the scripts students
   run stay Bash": on a fresh Windows machine there is no Bash until Git for Windows is
   installed, so the first command has to be PowerShell.
2. **A thin platform layer over shared Python.** Only steps 1 to 7 (plan, system tools, user
   tools, agent, git identity, logins, clone) differ per platform and live in the two entry
   points. Steps 8 and 9 (git hooks, every session synced from its lockfile, the setup check) are
   `setup/student/prepare.py`, standard-library Python run with
   `uv run --no-project --python 3.12`, shared by both (ADR 0010 prefers Python over shell). It
   discovers sessions by the contract `session-tests.yml` already enforces (`mise.toml`,
   `pyproject.toml`, `uv.lock`), so a new session needs no setup change.
   `setup/session-01-fundamentals.sh` stays, under its name, as a wrapper over that step.
3. **Bootstrap from `main`.** The one-liners fetch the scripts from `main` on
   `raw.githubusercontent.com`, and the script fetches `versions.env` from there too. `main` is
   protected and every change lands through the required CI check (ADR 0007), which runs the
   setup for real on each track it covers when the setup changes. The same scripts run from an
   existing clone, and the docs show how to download and read them first.
4. **What is pinned, and what is not.**
   - **Pinned in `setup/student/versions.env`:** uv, through its versioned installer URL; mise,
     through `MISE_VERSION`; and gh's macOS release archive, with its SHA-256. These are the
     tools whose installers can be pinned, and the course's reproducibility rule asks for it
     (AGENTS.md, "Reproducible tooling").
   - **Pinned per session:** Python and the session's uv in each session's `mise.toml`, and its
     packages in `uv.lock` (ADR 0001), so the student-wide tool versions never change what a
     session runs.
   - **Floors, not pins:** git and gh come from the platform's package source at whatever version
     it serves. A tool already at or above the floors of the setup check (`FLOORS` in
     `check_setup.py`, repeated in `versions.env` and tested to be equal) is left alone.
   - **Not pinned: Claude Code and Codex install their current release.** As of 2026-11-04,
     Claude Code's native installer installs the `latest` channel unless given `stable` or a
     version, and native installs then update themselves in the background
     (<https://code.claude.com/docs/en/setup>). Codex's installer installs the latest release
     unless `CODEX_RELEASE` names one, and updates by rerunning it; a latest install is marked
     for its automatic updates (<https://developers.openai.com/codex/cli>, and the installer at
     <https://chatgpt.com/codex/install.sh>). A pin would last only until the first automatic
     update, and new models need recent CLI versions, so pinning would buy no reproducibility
     and would cost students features. The setup check's smoke test proves the installed agent
     works.
5. **Proof.** `tests/student_setup` checks every track's plan through simulated detection, the
   rerun, an existing clone left untouched, session discovery and the static constraints.
   `.github/workflows/student-setup.yml` runs the non-interactive setup twice, for real, in pinned
   Ubuntu LTS, Debian, Fedora and Arch containers, on `macos-latest` with `/bin/bash` and on
   `windows-latest` with Windows PowerShell 5.1. It runs on pull requests that change the setup
   (`[units.student-setup]` in `tools/test-impact/impact.toml`) and on every full run. What CI
   cannot do, real logins and GUI prompts, is a live run by a person, recorded per track in
   `setup/student/verification.md`; a track without one is labeled untested.

## Consequences

- A student's setup is one command; the per-tool commands stay on the pre-work page as the
  manual fallback.
- The setup changes students' machines: it installs packages (with `sudo` or an administrator
  prompt, always named in the plan first) and lets the official installers edit `PATH`. It never
  stores a secret and never sets or unsets `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.
- Two entry points must stay in step; the shared Python step and the tests keep that small.
- The student-setup CI jobs take several minutes and download real installers, so they run only
  when the setup or what it reads changes, and nightly.
- Bumping uv, mise or gh is an edit to `versions.env` (see `setup/student/README.md`); bumping a
  container image is an edit to `student-setup.yml` and the verification record.
