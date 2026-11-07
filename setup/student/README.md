# Students: prepare your machine

One command for your platform takes a machine from fresh to ready for the course. It asks a few
questions and opens your browser to log in. When it is done you have git, the GitHub CLI (`gh`),
uv, mise and your agent (Claude Code, Codex, or both), your git identity, logins to GitHub and
to your agent, the course cloned with its git hooks active, every session's Python environment,
and the setup check's summary block on screen.

Rerunning the same command is safe: it skips what is done and continues from what is missing.
If a step fails, it says which step, why, and the exact command to run next.

**Before you start, you need:**

- a [GitHub account](https://github.com/signup);
- a Claude plan that includes Claude Code (Pro, Max, Team, Enterprise, or a Claude Console
  account), or a ChatGPT plan that includes Codex. One agent is enough; the course works with
  either one;
- your own computer, on which you can approve `sudo` (macOS and Linux) or administrator (UAC)
  prompts. The setup asks for them only to install system packages, and says so before it runs.

If you prefer to install each tool by hand, follow "Install the tools" on the pre-work page,
[`00-prework.html`](../../sessions/01-fundamentals/exercises/00-prework.html). It gives each
tool's official commands, and the setup check there verifies the result the same way.

## The command for your platform

| Your machine | Open | Run |
| --- | --- | --- |
| [Windows 10 or 11](#windows-powershell) | PowerShell (not as administrator) | `irm https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.ps1 \| iex` |
| [Windows, working in WSL 2](#windows-with-wsl-2) | your WSL terminal (for example Ubuntu) | `curl -fsSL https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.sh \| bash` |
| [macOS](#macos) | Terminal | `curl -fsSL https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.sh \| bash` |
| [Debian, Ubuntu](#debian--ubuntu), [Fedora](#fedora), [Arch](#arch) and [other Linux](#other-linux) | a terminal | `curl -fsSL https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.sh \| bash` |

No flags are needed. If your machine has no `curl` (some minimal Linux installs), use `wget`:

```sh
wget -qO- https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.sh | bash
```

Already have a clone? Run the same script from it: `bash setup/student/install.sh`, or on
Windows `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup\student\install.ps1`. It then
uses that clone and never pulls, resets, switches or commits anything in it.

When it finishes, copy the summary block (both marker lines included) into the form your
instructor gives you, open the pre-work page for the reading, and open a **new** terminal window
so that `PATH` includes the new tools.

### Read the script before you run it

Piping a script from the internet into a shell runs it unread. To read it first, download it,
open it, then run the file:

```sh
curl -fsSL https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.sh -o install.sh
less install.sh
bash install.sh --dry-run    # prints the plan and changes nothing
bash install.sh
```

```powershell
irm https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.ps1 -OutFile install.ps1
notepad install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -DryRun
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

Downloaded this way, the script fetches [`versions.env`](versions.env) (the pinned versions) from
the same place. After the clone, it runs [`prepare.py`](prepare.py) from the clone.

### What it does, in order

1. **Plan.** It names your track, then lists each tool: already there (and at which version), or
   what it will install, from where and into which folder, and which commands use `sudo`, an
   administrator prompt or a macOS dialog. You confirm once.
2. **System tools.** git and gh, and on Linux `curl`, `tar`, `gzip` and `awk` if the official
   installers need them and they are missing.
3. **User tools.** uv and mise, from their official installers, at the versions pinned in
   [`versions.env`](versions.env).
4. **Agent.** It asks which agent you use, then installs it with its official native installer
   (not npm).
5. **git identity.** It asks for your name and email if `user.name` or `user.email` is not set
   (with `--yes --no-login` it asks nothing, and prints the two `git config` commands instead).
6. **Logins**, in your browser: `gh auth login` (GitHub.com, HTTPS, gh as git's credential
   helper), then your agent's login. Each is skipped if you are already logged in. The setup never
   prints or stores a token or an API key.
7. **Clone** the course into `~/coding-agent-cursus`, or reuse the clone it runs from.
8. **Prepare the clone.** It activates the git hooks, then in every session runs `mise trust`,
   `mise install` and `mise exec -- uv sync --locked`, including the default ty checker. It syncs
   repository tools into `setup/.venv` and, when VS Code's `code` CLI is available, installs and
   verifies the Python and ty extensions pinned in [`../editor.json`](../editor.json). Checked-in
   settings select the right Python environment and checker; no user settings are rewritten.
   Open `setup/cursus.code-workspace` for the whole course, or a session folder on its own.
   Without VS Code, editor installation is explicitly skipped. See [editor setup](../README.md#vs-code).
   It changes no tracked file in the clone: a hook
   that is not executable is reported, with the `chmod +x` command that fixes it.
9. **Check.** It runs the latest session's setup check, which tests the logins, a push and your
   agent, and shows its summary block.

Every tool already at or above the version the setup check requires (git 2.23, gh 2.0, uv 0.5,
mise 2024.1.0; any version of the agents) is left alone: no upgrade and no second copy. After an
install, the setup checks the version it now finds. If an older copy earlier on your `PATH`
hides the new one in `~/.local/bin`, it uses the new one and tells you to remove the older one.
If a tool is still below its version, it stops at that step with the command to run next.

### Options

You never need them. Each one also has an environment-variable form, because
`irm ... | iex` cannot pass arguments: on Windows, set it first, for example
`$env:CURSUS_AGENT = 'codex'`. With `curl ... | bash`, pass flags after `bash -s --`, for example
`curl -fsSL <url> | bash -s -- --agent codex`.

| install.sh | install.ps1 | Environment | Effect |
| --- | --- | --- | --- |
| `--agent claude\|codex\|both` | `-Agent` | `CURSUS_AGENT` | which agent to install, instead of asking |
| `--yes` | `-Yes` | `CURSUS_YES=1` | do not ask to confirm the plan |
| `--no-login` | `-NoLogin` | `CURSUS_NO_LOGIN=1` | skip the logins and the setup check; the output says so |
| `--dry-run` | `-DryRun` | `CURSUS_DRY_RUN=1` | print the plan and change nothing |
| `--dir DIR` | `-Dir DIR` | `CURSUS_DIR` | clone somewhere other than `~/coding-agent-cursus` |

With `--yes --agent <a> --no-login` it runs without a single prompt (this is how CI runs it).
Without a terminal it stops with a message, unless it has those three. It never sets or unsets
`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`; it only warns, without showing the value, when
`ANTHROPIC_API_KEY` is set, because Claude Code would use that key instead of your subscription.

## Tracks

Supported versions, as of 2026-11-04, are where the course's tools and both agents' official
installers support them ([sources](#sources)): Claude Code supports macOS 13+, Windows 10 1809+
or Windows Server 2019+, Ubuntu 20.04+, Debian 10+ and Alpine 3.19+, on x64 or ARM64 with 4 GB of
RAM or more. Codex ships macOS (Apple silicon and Intel), Linux (x86_64 and ARM64) and Windows
(x64 and ARM64) builds; on Windows, OpenAI recommends Windows 11 and supports a fully updated
Windows 10 1809+ on a best-effort basis. In each track's status, "tested in CI" means the
non-interactive run (`--yes --agent both --no-login`, twice) passes in CI; a live run is a
person's full interactive run with real logins and the setup check passing. A track with no live
run is labeled untested.

### Windows (PowerShell)

**Status:** CI: tested in CI. Live run: untested. CI runs it on `windows-latest` with Windows
PowerShell 5.1, where git and gh are already installed.

- **Command**, in PowerShell (not as administrator), Windows PowerShell 5.1 or PowerShell 7:
  `irm https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.ps1 | iex`
- **Supported:** Windows 10 version 1809 or later, or Windows 11, x64 or ARM64, with winget (App
  Installer, included in current Windows). Codex works best on Windows 11.
- **Installs:**
  - git: Git for Windows, which includes Git Bash (Claude Code uses it), with
    `winget install --id Git.Git -e --source winget --scope user`, into
    `%LOCALAPPDATA%\Programs\Git`;
  - gh: `winget install --id GitHub.cli -e --source winget --scope user`, winget's per-user
    package under `%LOCALAPPDATA%\Microsoft\WinGet`;
  - uv: `irm https://astral.sh/uv/<UV_VERSION>/install.ps1 | iex`, into `~\.local\bin`;
  - mise: mise's own PowerShell installer, `irm https://mise.run/powershell | iex` with
    `MISE_VERSION` set, into `~\.local\bin`, for your user only (no administrator rights);
  - Claude Code: `irm https://claude.ai/install.ps1 | iex`, into `~\.local\bin\claude.exe` and
    `~\.local\share\claude`;
  - Codex: `irm https://chatgpt.com/codex/install.ps1 | iex`, into
    `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin`.

  The installers add their folders to your **user** `Path` environment variable; the setup
  prints each folder added and refreshes `Path` in the same window after every install.
- **Administrator prompts:** Git for Windows' installer asks for administrator approval (UAC)
  even for a per-user install: approve it. If you decline, the setup stops and tells you to
  install Git from <https://git-scm.com/install/windows> instead, then rerun. winget may also ask
  for approval for gh. Nothing else needs administrator rights.
- **Undo:** `winget uninstall --id Git.Git` and `winget uninstall --id GitHub.cli` (only if the
  setup installed them); uv: `uv cache clean`, then delete `~\.local\bin\uv.exe`, `uvx.exe` and
  `uvw.exe`; mise: `mise implode`; Claude Code: delete `~\.local\bin\claude.exe` and
  `~\.local\share\claude`; Codex: delete `%LOCALAPPDATA%\Programs\OpenAI\Codex` and `~\.codex`;
  then remove the folders above from your user `Path` (Settings, "Edit environment variables for
  your account"), and delete `~\coding-agent-cursus`.

### Windows with WSL 2

**Status:** CI: not in CI. Live run: untested. CI runs the same script on Ubuntu, and the
detection of WSL is tested offline; the record lists a non-interactive run on WSL 2.

- **Command**, inside your WSL terminal, not in PowerShell:
  `curl -fsSL https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.sh | bash`
- **Supported:** WSL 2 with its default Ubuntu (install it with
  [Microsoft's WSL guide](https://learn.microsoft.com/windows/wsl/install)), on Windows 10 or 11.
  Other WSL distributions follow their Linux track below.
- **Installs:** everything inside WSL, exactly as the [Debian / Ubuntu](#debian--ubuntu) track.
  Keep the clone in the Linux filesystem (`~/coding-agent-cursus`, the default): the setup warns
  if it would land under `/mnt/`, the Windows drive, where git and Python are slow.
- **sudo:** as for Debian / Ubuntu.
- **Undo:** as for Debian / Ubuntu, inside WSL.

### macOS

**Status:** CI: tested in CI. Live run: untested. CI runs it on `macos-latest` (Apple silicon)
with `/bin/bash`, Bash 3.2, where git and gh are already installed.

- **Command**, in Terminal:
  `curl -fsSL https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.sh | bash`
- **Supported:** macOS 13 or later, Apple silicon or Intel. Homebrew is not required.
- **Installs:**
  - git: from Apple's Xcode Command Line Tools. If they are missing, the setup runs
    `xcode-select --install`, which opens a dialog, and stops: finish the dialog, then rerun the
    same command;
  - gh: with `brew install gh` if you already have Homebrew; otherwise GitHub's release archive
    `gh_<GH_VERSION>_macOS_<arm64|amd64>.zip`, checked against the SHA-256 pinned in
    [`versions.env`](versions.env), into `~/.local/share/coding-agent-cursus/gh/<GH_VERSION>/`,
    linked as `~/.local/bin/gh`;
  - uv: `curl -LsSf https://astral.sh/uv/<UV_VERSION>/install.sh | sh`, into `~/.local/bin`;
  - mise: `curl -fsSL https://mise.run | MISE_VERSION=<MISE_VERSION> sh`, into `~/.local/bin`;
  - Claude Code: `curl -fsSL https://claude.ai/install.sh | bash`, into `~/.local/bin/claude` and
    `~/.local/share/claude`;
  - Codex: `curl -fsSL https://chatgpt.com/codex/install.sh | sh`, into `~/.local/bin/codex`
    and `~/.codex`.

  uv's and Codex's installers add `~/.local/bin` to `PATH` in your shell startup files (for
  example `~/.zshrc` or `~/.zprofile`); the setup prints which files changed. It does not add
  mise's shell activation, which the course does not need.
- **sudo or dialogs:** only the Command Line Tools dialog; nothing uses sudo.
- **Undo:** `brew uninstall gh`, or `rm -rf ~/.local/share/coding-agent-cursus/gh ~/.local/bin/gh`;
  uv: `uv cache clean`, then `rm ~/.local/bin/uv ~/.local/bin/uvx`; mise: `mise implode`;
  Claude Code: `rm -f ~/.local/bin/claude; rm -rf ~/.local/share/claude`; Codex:
  `rm -f ~/.local/bin/codex; rm -rf ~/.codex`; delete the `PATH` lines the installers added to
  your startup files, and `rm -rf ~/coding-agent-cursus`. The Command Line Tools are part of
  macOS's developer setup; leave them.

### Debian / Ubuntu

**Status:** CI: tested in CI. Live run: untested. CI runs it in clean `ubuntu:26.04` and
`debian:13.7` containers.

- **Command:** `curl -fsSL https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.sh | bash`
  (also Linux Mint, Pop!_OS and other derivatives).
- **Supported:** Ubuntu 20.04 or later and Debian 10 or later (Claude Code's minimum), x86_64 or
  ARM64.
- **Installs:** git, and `curl`, `tar`, `gzip` or `gawk` if missing, with `apt-get`; gh from
  GitHub's apt repository (its signing key in `/etc/apt/keyrings/githubcli-archive-keyring.gpg`,
  the repository in `/etc/apt/sources.list.d/github-cli.list`), all into `/usr/bin`. uv, mise,
  Claude Code and Codex as on macOS, into `~/.local/bin`; uv's and Codex's installers add it to
  `PATH` in `~/.bashrc` or `~/.profile`, and the setup prints which files changed.
- **sudo:** only `apt-get update`, `apt-get install` and the two repository files for gh. The
  plan lists each command before anything runs.
- **Undo:** `sudo apt-get remove gh` (and git, if the setup installed it), then
  `sudo rm /etc/apt/sources.list.d/github-cli.list /etc/apt/keyrings/githubcli-archive-keyring.gpg`;
  then uv, mise, Claude Code, Codex and the clone as on macOS.

### Fedora

**Status:** CI: tested in CI. Live run: untested. CI runs it in a clean `fedora:45` container.

- **Command:** `curl -fsSL https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.sh | bash`
- **Supported:** current Fedora releases, which use DNF5 (Fedora 41 or later), x86_64 or ARM64.
- **Installs:** git, and `curl`, `tar`, `gzip` or `gawk` if missing, with `dnf`; gh from
  GitHub's rpm repository (`dnf config-manager addrepo --from-repofile=https://cli.github.com/packages/rpm/gh-cli.repo`,
  after `dnf install dnf5-plugins`), into `/usr/bin`. The user tools as on Debian / Ubuntu.
- **sudo:** only those `dnf` commands, listed in the plan.
- **Undo:** `sudo dnf remove gh`, `sudo rm /etc/yum.repos.d/gh-cli.repo`; then the user tools
  and the clone as on macOS.

### Arch

**Status:** CI: tested in CI. Live run: untested. CI runs it in a clean
`archlinux:base-20261101.0.620205` container.

- **Command:** `curl -fsSL https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.sh | bash`
  (also Manjaro, EndeavourOS and other derivatives).
- **Supported:** Arch Linux, rolling, x86_64.
- **Installs:** `git` and `github-cli` (and `curl`, `tar`, `gzip` or `gawk` if missing) with
  `pacman -S --needed`, into `/usr/bin`. A machine whose package database was never synced gets
  `pacman -Sy` first. The user tools as on Debian / Ubuntu.
- **sudo:** only those `pacman` commands, listed in the plan. If `pacman` cannot find a package,
  update the system with `sudo pacman -Syu`, then rerun.
- **Undo:** `sudo pacman -R github-cli`; then the user tools and the clone as on macOS.

### Other Linux

**Status:** CI: not in CI. Live run: untested. Its detection and plan are tested offline.

- **Command:** `curl -fsSL https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.sh | bash`
- **Supported:** any other distribution on x86_64 or ARM64, if you install git, gh and curl
  yourself. When one is missing, the setup stops at the system tools step and points to the
  manual commands: [git](https://git-scm.com/install/linux),
  [gh](https://github.com/cli/cli/blob/trunk/docs/install_linux.md), and "Install the tools" on
  the pre-work page. Once they are installed, the same command continues.
- **Installs and undo:** the user tools as on Debian / Ubuntu. Nothing uses sudo.

## After the setup: updating

- **Claude Code** updates itself in the background (native installs). `claude update` updates it
  now; `/config` chooses the `latest` (default) or `stable` release channel.
- **Codex:** rerun its installer, `curl -fsSL https://chatgpt.com/codex/install.sh | sh` (or the
  PowerShell line above), to update; an install of the latest release is also marked for its
  automatic updates.
- **uv, mise, git and gh** stay at the version installed until you update them: `uv self update`,
  `mise self-update`, and your package manager (or `brew upgrade gh`, `winget upgrade`).

The course pins the Python and uv each session uses in that session's `mise.toml`, so updating
the tools above never changes what a session runs.

## Bump the pins

For maintainers. [`versions.env`](versions.env) is the one place for the setup's pinned versions:

- `UV_VERSION`: a uv release from <https://github.com/astral-sh/uv/releases>; check that
  `https://astral.sh/uv/<version>/install.sh` and `install.ps1` exist.
- `MISE_VERSION`: a mise release tag (with its `v`) from <https://github.com/jdx/mise/releases>.
  Both mise installers check the archive against that release's `SHASUMS256.txt`.
- `GH_VERSION`, `GH_MACOS_ARM64_SHA256`, `GH_MACOS_AMD64_SHA256`: a gh release from
  <https://github.com/cli/cli/releases>, and the two `macOS_*.zip` lines of its
  `gh_<version>_checksums.txt`.
- The floors (`*_FLOOR`) must equal `FLOORS` in the latest session's `exercises/check_setup.py`;
  `tests/student_setup/test_static.py` fails when they differ.

Then run `uv run --no-project --with pytest==8.3.5 pytest -q tests/student_setup` and open a pull
request: CI runs the setup for real on every track it covers. Pinned container images live in
`.github/workflows/student-setup.yml`; when you bump one, change the image named in that
track's status above too.

## Sources

Checked on 2026-11-04. See [ADR 0015](../../docs/adr/0015-student-setup-one-command-per-platform.md)
for what is pinned and why.

| Topic | Source | What it says |
| --- | --- | --- |
| Claude Code | <https://code.claude.com/docs/en/setup> | System requirements above; native install `curl -fsSL https://claude.ai/install.sh \| bash` and `irm https://claude.ai/install.ps1 \| iex`; the installer takes `stable`, `latest` (default) or a version; native installs update in the background; launcher `~/.local/bin/claude` into `~/.local/share/claude`; uninstall by deleting those. |
| Claude Code login | <https://code.claude.com/docs/en/cli-reference> | `claude auth status` exits 0 when logged in, 1 when not; `claude auth login` signs in. |
| Codex | <https://developers.openai.com/codex/cli> | Install, and update, with `curl -fsSL https://chatgpt.com/codex/install.sh \| sh`; Windows `irm https://chatgpt.com/codex/install.ps1 \| iex`. The installer (read on the same date) defaults to the latest release (`CODEX_RELEASE` picks one), installs into `~/.local/bin`, or `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin` on Windows, and skips its prompts with `CODEX_NON_INTERACTIVE=1`. |
| Codex on Windows | <https://developers.openai.com/codex/windows> | Windows 11 recommended; recent, fully updated Windows 10 1809+ best effort; winget should be available. |
| Codex builds | <https://github.com/openai/codex> | Release archives for macOS arm64 and x86_64, Linux x86_64 and arm64 (musl), Windows x64 and arm64. |
| uv | <https://docs.astral.sh/uv/getting-started/installation/> | Standalone installers; a versioned URL `https://astral.sh/uv/<version>/install.sh` installs that version into `~/.local/bin` and adds it to `PATH` in shell profiles (on Windows, the user `Path`); uninstall with `uv cache clean` and deleting the binaries. |
| mise | <https://mise.jdx.dev/installing-mise.html> | `curl -fsSL https://mise.run \| sh` into `~/.local/bin/mise`; `MISE_VERSION` pins a release, checked against GitHub's `SHASUMS256.txt`; on Windows, winget (`jdx.mise`) or the PowerShell script `irm https://mise.run/powershell \| iex`, which installs to `~\.local\bin` and adds it to the user `Path` with no admin rights. |
| Git for Windows (winget) | <https://github.com/microsoft/winget-pkgs/tree/master/manifests/g/Git/Git> | `Git.Git` has user- and machine-scope installers and `ElevationRequirement: elevatesSelf`: it asks for elevation itself. |
| GitHub CLI (winget) | <https://github.com/microsoft/winget-pkgs/tree/master/manifests/g/GitHub/cli> | `GitHub.cli` offers a machine-scope MSI and a portable zip, which winget installs per user. |
| GitHub CLI on Linux and macOS | <https://github.com/cli/cli/blob/trunk/docs/install_linux.md>, <https://github.com/cli/cli/blob/trunk/docs/install_macos.md> | The apt repository commands (Debian, Ubuntu), DNF5 commands (Fedora), `pacman -S github-cli` (Arch); precompiled macOS archives on the releases page. |
| Git | <https://git-scm.com/install/mac>, <https://git-scm.com/install/linux>, <https://git-scm.com/install/windows> | git from the Xcode Command Line Tools on macOS, from the distribution's packages on Linux, Git for Windows through winget. |
