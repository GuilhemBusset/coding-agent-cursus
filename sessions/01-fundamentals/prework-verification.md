# Pre-work verification record

Evidence behind [`exercises/00-prework.html`](exercises/00-prework.html) and its setup check
(`exercises/check-setup.sh`, `exercises/check-setup.ps1`, `exercises/check_setup.py`). This file
sits outside `exercises/` on purpose: turn-in pushes `exercises/` to public homework branches.

A dated row in the source tables means the official page was read on that date and the command
on the page matches it. It does not mean the command was run on that platform. Which platforms
the check itself has run on is in [Platform status](#platform-status).

## Platform status

"Tested" means a full real run of the setup check (real `gh` login, network, push to the course
repo or a fork, and a real agent), done once with Claude Code alone and once with Codex alone,
with both summary blocks recorded below together with the OS, kernel, script hash and CLI
versions. Anything less is listed as untested on the page.

| Platform | Status | Evidence |
| --- | --- | --- |
| Native Linux | untested | No full run on a native Linux kernel recorded. |
| WSL 2 (Ubuntu 26.04) | untested | Fixture-tested on WSL2 only (see [Fixture runs on WSL2](#fixture-runs-on-wsl2)): real git, uv and agents, local stand-ins for gh, the network and GitHub. No full real run recorded: the implementation loop's agent is not permitted to use `gh` on this host (its `gh auth status` calls were denied on 2026-10-10, and denied again on a later attempt the same day), so it cannot make the real login check and push. Running `check-setup.sh` itself would make those same `gh` calls and push to GitHub, so the agent did not do that either. The owner's run is pending. |
| macOS | untested | No run recorded. |
| Windows PowerShell 5.1 | untested | `check-setup.ps1` parses under PowerShell 7.6.6 with no 7-only syntax (test `test_ps51_syntax_and_launch_contract`); never run on Windows. |
| Windows Git Bash | untested | No run recorded. |

To record a full run, on the platform itself, from the root of a course clone, once with only
Claude Code on `PATH` and once with only Codex:

```sh
bash sessions/01-fundamentals/exercises/check-setup.sh
```

Paste both summary blocks under a new heading here with the date, `uname -a` (or the Windows
version), `sha256sum` of the three scripts, and `claude --version` / `codex --version`. Then set
that platform's `data-status` to `tested` on the page and its row above to `tested`.

## Install sources

Every install block on the page (`[data-install]`), one row each. "Platform and shell" uses the
block's `data-platform` values.

| Tool | Platform and shell | Command on the page | Official source | What the source says | Checked |
| --- | --- | --- | --- | --- | --- |
| git | macos (Terminal) | `xcode-select --install`<br>`brew install git` | https://git-scm.com/install/mac | Git ships with Apple's Xcode Command Line Tools (`xcode-select --install`); with Homebrew, `brew install git`. | 2026-10-10 |
| git | linux, wsl (bash) | `sudo apt-get install git`<br>`sudo dnf install git` | https://git-scm.com/install/linux | Debian/Ubuntu: `# apt-get install git`; Fedora 22 and later: `# dnf install git` (shown as root; the page uses `sudo`). | 2026-10-10 |
| git | windows (PowerShell) | `winget install --id Git.Git -e --source winget` | https://git-scm.com/install/windows | "Using winget tool": `winget install --id Git.Git -e --source winget`, or the 64-bit installer (2.56.0(2), released 2026-10-05). Git for Windows includes Git Bash. | 2026-10-10 |
| gh | macos (Terminal) | `brew install gh` | https://github.com/cli/cli/blob/trunk/docs/install_macos.md#homebrew | Homebrew: `brew install gh`. | 2026-10-10 |
| gh | linux, wsl (bash) | `(type -p wget >/dev/null \|\| (sudo apt update && sudo apt install wget -y)) \ && sudo mkdir -p -m 755 /etc/apt/keyrings \ && out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg \ && cat $out \| sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \ && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \ && sudo mkdir -p -m 755 /etc/apt/sources.list.d \ && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \| sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \ && sudo apt update \ && sudo apt install gh -y`<br>`sudo dnf install dnf5-plugins`<br>`sudo dnf config-manager addrepo --from-repofile=https://cli.github.com/packages/rpm/gh-cli.repo`<br>`sudo dnf install gh` | https://github.com/cli/cli/blob/trunk/docs/install_linux.md#debian and https://github.com/cli/cli/blob/trunk/docs/install_linux.md#dnf5 | Debian/Ubuntu: the official apt repository, installed with exactly this command (the page indents with spaces instead of tabs); Fedora DNF5: these three commands. The packages' signing key rotated on 2026-09-05 (cli.github.com banner). | 2026-10-10 |
| gh | windows (PowerShell) | `winget install --id GitHub.cli --source winget` | https://github.com/cli/cli/blob/trunk/docs/install_windows.md#winget | WinGet (official): `winget install --id GitHub.cli --source winget`; open a new Windows Terminal window afterwards, not a new tab. | 2026-10-10 |
| uv | macos, linux, wsl (sh) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | https://docs.astral.sh/uv/getting-started/installation/ | Standalone installer, macOS and Linux: `curl -LsSf https://astral.sh/uv/install.sh \| sh`. | 2026-10-10 |
| uv | windows (PowerShell) | `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"` | https://docs.astral.sh/uv/getting-started/installation/ | Standalone installer, Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 \| iex"`. | 2026-10-10 |
| mise | macos, linux, wsl (sh) | `curl -fsSL https://mise.run \| sh`<br>`brew install mise` | https://mise.jdx.dev/getting-started.html and https://mise.jdx.dev/installing-mise.html#homebrew | "On macOS or Linux, run the installer: `curl -fsSL https://mise.run \| sh`", which puts `mise` at `~/.local/bin/mise`; Homebrew: `brew install mise`. Shell activation is optional. | 2026-10-10 |
| mise | windows (PowerShell) | `winget install jdx.mise` | https://mise.jdx.dev/installing-mise.html#windows-winget | "winget is the recommended method on Windows": `winget install jdx.mise`. | 2026-10-10 |
| claude | macos, linux, wsl (bash) | `curl -fsSL https://claude.ai/install.sh \| bash` | https://code.claude.com/docs/en/setup | Native install, "macOS, Linux, WSL": `curl -fsSL https://claude.ai/install.sh \| bash`. In WSL, install and launch inside the WSL terminal. Requires a Pro, Max, Team, Enterprise or Console account. | 2026-10-10 |
| claude | windows (PowerShell) | `irm https://claude.ai/install.ps1 \| iex` | https://code.claude.com/docs/en/setup | Native install, "Windows PowerShell": `irm https://claude.ai/install.ps1 \| iex`; no administrator needed; with Git for Windows, Claude Code uses Git Bash for its Bash tool. | 2026-10-10 |
| codex | macos, linux, wsl (sh) | `curl -fsSL https://chatgpt.com/codex/install.sh \| sh`<br>`brew install --cask codex`<br>`npm install -g @openai/codex` | https://developers.openai.com/codex/cli | Install tabs: "macOS/Linux" standalone installer `curl -fsSL https://chatgpt.com/codex/install.sh \| sh`; "Homebrew" `brew install --cask codex`; "npm" `npm install -g @openai/codex`. The WSL page uses the same Linux installer inside WSL. The npm package is `@openai/codex`; plain `codex` on npm is a different package. | 2026-10-10 |
| codex | windows (PowerShell) | `powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 \| iex"`<br>`npm install -g @openai/codex` | https://developers.openai.com/codex/cli and https://github.com/openai/codex | "Windows" tab, "Start these from a new PowerShell window": `powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 \| iex"` (same line in the README); npm alternative `npm install -g @openai/codex`. https://developers.openai.com/codex/windows: the CLI runs natively with a Windows sandbox. | 2026-10-10 |

Other sources the page relies on, read on 2026-10-10:

| Topic | Source | What it says |
| --- | --- | --- |
| Claude Code login | https://code.claude.com/docs/en/authentication | If the browser does not open, press `c` to copy the login URL and paste it into a browser; if the browser shows a code instead (common in WSL2), paste it at `Paste code here if prompted`. With `ANTHROPIC_API_KEY` set, the key is used once approved and always in `-p` mode; "Run `unset ANTHROPIC_API_KEY` to fall back to your subscription". |
| Codex login | https://developers.openai.com/codex/auth | `codex login`; on headless setups or when the localhost callback is blocked, device code login (beta): enable it in ChatGPT security settings, run `codex login --device-auth`, open the link and enter the code. |
| WSL itself | https://learn.microsoft.com/windows/wsl/install | Linked for installing WSL 2; not an install block. |
| PowerShell 7 for the tests | https://github.com/PowerShell/PowerShell/releases/tag/v7.6.6 | Pinned in `setup/pwsh.sh` with the linux-x64 and linux-arm64 SHA-256 from the release. |

## Reading sources

| Item | URL | Title and details as found | Checked |
| --- | --- | --- | --- |
| 3Blue1Brown | https://www.youtube.com/watch?v=LPZh9BOjkQs | "Large Language Models explained briefly", 3Blue1Brown, 7 min 58 s (YouTube oEmbed and page metadata). | 2026-10-10 |
| Karpathy, full video | https://www.youtube.com/watch?v=EWvNQjAaOHw | "How I use LLMs", Andrej Karpathy, 2 h 11 min 12 s; chapters from the video description. | 2026-10-10 |
| Karpathy, chapter | https://www.youtube.com/watch?v=EWvNQjAaOHw&t=174s | Chapter "ChatGPT interaction under the hood", 00:02:54 to 00:13:12. | 2026-10-10 |
| Karpathy, chapter | https://www.youtube.com/watch?v=EWvNQjAaOHw&t=1374s | Chapter "Thinking models and when to use them", 00:22:54 to 00:31:00. | 2026-10-10 |
| Karpathy, chapter | https://www.youtube.com/watch?v=EWvNQjAaOHw&t=1860s | Chapter "Tool use: internet search", 00:31:00 to 00:42:04. | 2026-10-10 |
| Karpathy, chapter | https://www.youtube.com/watch?v=EWvNQjAaOHw&t=4442s | Chapter "Cursor: Composer, writing code", 01:14:02 to 01:22:28. | 2026-10-10 |
| Claude Code course | https://anthropic.skilljar.com/claude-code-101 | "Claude Code 101", Anthropic Academy (Skilljar); 12 lessons and a quiz, from "What is Claude Code?" to "Hooks"; lesson estimates on the page add up to about 2 hours. | 2026-10-10 |
| Codex course | https://academy.openai.com/public/courses/get-started-with-codex-jkhsq | "Get Started with Codex", OpenAI Academy, "Duration: ~80 minutes"; the first of the Codex courses listed on https://academy.openai.com/pages/courses (then "Extend Codex workflows", "Scale Codex across teams and systems"). | 2026-10-10 |

## Automated evidence

All on the WSL2 host described below, 2026-10-10.

### Host

- OS: Ubuntu 26.04 LTS on WSL2, kernel `6.18.33.2-microsoft-standard-WSL2`.
- git 2.53.0, uv 0.11.28, Python 3.12.13 (uv-managed), PowerShell 7.6.6 (`bash setup/pwsh.sh`).
- Claude Code 2.1.302, Codex CLI 0.162.1 (`codex exec --skip-git-repo-check --output-last-message` used by the smoke test).
- Script hashes (SHA-256): `check_setup.py` dd9e44d52105a696613f5579249bb25abe6809d6bff95cdc8a1af3887cb10e98,
  `check-setup.sh` 34751e3dc317c83bfc811211de3075ddbe42712a96c5413dbc22edf7b851c4e7,
  `check-setup.ps1` e9d5ff997e502be53389da0fceeb556fe91a857f9c38995d4e96d5f8db7e45ab.

### Wrapper fallback

Each wrapper streams the checker's output and passes its exit status through only if the
`----- END SETUP SUMMARY -----` line appeared. Otherwise it prints its own presence-only report
and summary block and exits 1. That covers uv missing, uv exiting with another code, and Python
that fails to start and exits 1 (for example a stale `PYTHONHOME`). The examiner's probe
`python3 tests/probe_prework_examiner.py Probe.test_D2_bootstrap_exit_one_summary` (from the repo
root) checks the last case with real uv through both entry points.

### Fixture runs on WSL2

`PATH="$HOME/.local/bin:$PATH" uv run --locked pytest -q tests/test_prework.py` runs every
scenario through both `bash check-setup.sh` and `pwsh -File check-setup.ps1` in a disposable
clone, with real git and uv, stub gh, mise and agents, a local HTTP server for the network, and
local bare repositories (with pre-receive hooks) standing in for the course repo and the fork.
This is fixture-tested on WSL2, not a full real run.

### Push cleanup

The push probe is a parentless, empty-tree commit whose message carries a random per-run line,
so two runs never produce the same commit, even in the same second. It is pushed without force,
so an existing `setup-check/<handle>` branch is never overwritten (the push is refused). After
`git ls-remote` shows the probe arrived, or when `ls-remote` cannot be read, the branch is
deleted with `git push --force-with-lease=refs/heads/setup-check/<handle>:<probe> <url>
:refs/heads/setup-check/<handle>`. Git only deletes it while it still holds this run's commit.
If the branch holds a different commit, nothing is deleted, and a `note:` says the branch was
left alone and gives no delete command. If the probe is still there after the delete, the note
gives the `gh api -X DELETE` command. If the branch cannot be read, the note says to delete it
only if it still points at the probe's first 12 hex digits. Cleanup never turns `push` into
FAIL. `push` passes only when `ls-remote` shows the probe.

`PATH="$HOME/.local/bin:$PATH" uv run --locked pytest -q tests/test_prework_cleanup.py` proves
this through both entry points against real local bare repositories. Covered:
a branch moved before verification, a branch moved between verification and the delete (the
lease refuses it), same-second runs, a pre-existing empty-tree branch with the old fixed message,
and unreadable `ls-remote` after the delete or at verification. In every case `main` and
`homework/*` stay untouched.

On 2026-10-17, `PATH="$HOME/.local/bin:$PATH" uv run --locked pytest -q tests/test_prework.py
tests/test_prework_cleanup.py` passed 171 tests in 182.5 s. The four agent smoke-timeout
scenarios set `CHECK_SETUP_SMOKE_TIMEOUT=5`, the documented override of the checker's 180 s
default, so they no longer wait three minutes each. The session suite runs in CI
(`.github/workflows/session-tests.yml`), where none of these tests may skip.

### A1: each agent alone, live

`PATH="$HOME/.local/bin:$PATH" uv run --locked python tests/prework_live_agents.py`: the real
`claude`, then the real `codex`, each alone on a `PATH` made only of symlinks (no `/usr/bin`; the
other agent is asserted absent). gh, the network and the push are local fixtures, so these blocks
prove A1, not a full real run. All four exited 0 (run on 2026-10-17).

Claude Code only, `check-setup.sh` (the PowerShell entry point printed the same lines):

```text
----- BEGIN SETUP SUMMARY -----
date: 2026-10-17 (UTC)
os: Linux (WSL)
kernel: 6.18.33.2-microsoft-standard-WSL2
python: 3.12.13
script: check_setup.py sha256 dd9e44d52105a696613f5579249bb25abe6809d6bff95cdc8a1af3887cb10e98
github: student-47
git: PASS 2.53.0 (>= 2.23.0)
git-identity: PASS user.name and user.email are set
gh: PASS 2.65.1 (>= 2.0.0)
gh-auth: PASS logged in to GitHub
uv: PASS 0.11.28 (>= 0.5.0)
mise: PASS 2025.3.2 (>= 2024.1.0)
network 127.0.0.1:<port>: PASS reachable (HTTP 200)
push: PASS to teaching-lab/course-24 (course repo)
claude: PASS 2.1.302
claude-smoke: PASS replied OK
codex: not installed (fine)
agent: PASS Claude Code
result: PASS
----- END SETUP SUMMARY -----
```

Codex only, `check-setup.ps1` under PowerShell 7.6.6 (the bash entry point printed the same lines):

```text
----- BEGIN SETUP SUMMARY -----
date: 2026-10-17 (UTC)
os: Linux (WSL)
kernel: 6.18.33.2-microsoft-standard-WSL2
python: 3.12.13
script: check_setup.py sha256 dd9e44d52105a696613f5579249bb25abe6809d6bff95cdc8a1af3887cb10e98
github: student-47
git: PASS 2.53.0 (>= 2.23.0)
git-identity: PASS user.name and user.email are set
gh: PASS 2.65.1 (>= 2.0.0)
gh-auth: PASS logged in to GitHub
uv: PASS 0.11.28 (>= 0.5.0)
mise: PASS 2025.3.2 (>= 2024.1.0)
network 127.0.0.1:<port>: PASS reachable (HTTP 200)
push: PASS to teaching-lab/course-24 (course repo)
claude: not installed (fine)
codex: PASS 0.162.1
codex-smoke: PASS replied OK
agent: PASS Codex
result: PASS
----- END SETUP SUMMARY -----
```

(`gh 2.65.1`, `mise 2025.3.2`, `student-47` and `teaching-lab/course-24` come from the fixtures.)

### Page

`node tools/html-pages/check-page.mjs sessions/01-fundamentals/exercises/00-prework.html`
(Chromium, external requests blocked, `file://`, desktop, laptop and mobile sizes) writes its
report and screenshots under `artifacts/html-pages/` in the repository root.
