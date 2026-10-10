# Repository setup

This directory is the home for repository-wide installation scripts, dependency manifests,
diagnostics, and setup documentation. Run the commands below from the repository root.
Installation needs internet access; viewing generated HTML needs only a browser.

## Every clone: activate git hooks

Prerequisites: Git and Bash (Git Bash on Windows).

```sh
bash setup/git-hooks.sh
```

This sets the clone's `core.hooksPath` to `.githooks/`, activating the protected-main checks.
It is safe to repeat. Run it yourself once per clone; agents do not activate it automatically.

## HTML authors: install browser tooling

Install [Node.js](https://nodejs.org/en/download) 22 or newer, including npm, then run:

```sh
node setup/html-pages.mjs
```

On a fresh supported Linux machine, include Chromium's OS libraries (may prompt for sudo):

```sh
node setup/html-pages.mjs --with-system-deps
```

The installer runs `npm ci --include=dev` against this directory's lockfile, downloads the
browser revision required by that Playwright version, and verifies offline `file://` rendering.
It resolves paths from its own location, so it also works from another directory when invoked
by its full path. Re-run after the lockfile changes; repeating it is safe. It does not activate
git hooks or change GitHub settings.

If you lack privileges to install Linux packages, ask the machine administrator to install
Playwright's Chromium dependencies, or, on Debian or Ubuntu, unpack them in user space with
[`browser-libs.py`](#browser-libraries-without-root). Setup reports failure until Chromium can
launch; there is no dependency on temporary libraries from an author's machine. See
[Playwright's browser documentation](https://playwright.dev/docs/browsers) for supported
environments, browser caches, and proxy/download configuration.

Verify the installation without reinstalling, then run the HTML tooling tests:

```sh
node setup/doctor.mjs
npm --prefix setup test
```

The tiny-lm suite also needs a C compiler on `PATH` as `cc` (OS-level; for example
`sudo apt-get install gcc` on Debian or Ubuntu, which GitHub's Ubuntu runners already have). It
compiles llama2.c's `run.c`, vendored at a pinned commit in
`sessions/01-fundamentals/cursus/labs/tiny-lm/reference/`, as the reference for the page's
logits. `node setup/doctor.mjs` reports the compiler and fails without it.

Check existing Cursus teaching pages with `npm --prefix setup run check-repo`. CI runs this
same setup and test sequence on Linux, the only platform teaching pages need (ADR 0010).

## Session 1: set up the session

Prerequisites: [mise](https://mise.jdx.dev/getting-started.html) and Bash (Git Bash on Windows).

```sh
bash setup/session-01-fundamentals.sh
```

Run it from the repository root as above; from any other directory, pass the script's path
(for example `bash ../../setup/session-01-fundamentals.sh` from inside the session). It resolves
the session from its own location, then, inside `sessions/01-fundamentals/`, runs
`mise trust mise.toml`, `mise install` (the Python and uv pinned in that session's `mise.toml`)
and `mise exec -- uv sync --locked` (the runtime dependencies from its `uv.lock`). It does not
install the build-only `fixtures` group. Repeating it is safe. The session's own
[README](../sessions/01-fundamentals/README.md) covers running and validating it.

## Claude Code and Codex

Use your installed, configured agent from the cloned repository. The repository supplies
`/html-page`, `/ship`, `/implement` and `/turn-in` through `.claude/skills/`, and `$html-page`,
`$ship`, `$implement` and `$turn-in` through `.agents/skills/`. No separate skill download or MCP
registration is needed.

## Students: turning in homework

Prerequisites: Git, Bash (Git Bash on Windows), and the [GitHub CLI](https://cli.github.com/)
(`gh`) logged in with `gh auth login`. `/turn-in <NN>`, `$turn-in <NN>` and
`scripts/turn-in.sh <NN>` push the session's `exercises/` folder to `homework/s<NN>/<handle>`
(see the root [README](../README.md#turning-in-homework) and
[ADR 0009](../docs/adr/0009-homework-on-per-student-branches.md)). Nothing else is installed.

CI runs the turn-in tests (`tests/turn_in/`, offline: throwaway repos and a fake `gh`) with uv
0.11.28, the version Session 1 pins, and the pytest version the engine tests pin. To run them
locally, with uv and `jq` installed:

```sh
uv run --no-project --with pytest==8.3.5 pytest -q tests/turn_in
```

## Running the implement loop

The implement loop (`scripts/implement.sh`, engine in `tools/implementation-loop/`) needs, on the
machine that runs it:

- Python 3.11 or newer (standard library only; nothing to install).
- Git, and the GitHub CLI authenticated with push access (`gh auth login`).
- **Both** agent CLIs, installed and logged in: Claude Code (`claude`) and Codex (`codex login`).
  The one that launches a run implements; the other reviews.
- The HTML browser tooling above, if the issues produce HTML pages. Node.js 22 or newer is the
  prerequisite; the loop repairs the rest itself, without `html-pages.mjs` (whose plain
  `npm ci` replaces `setup/node_modules` in place, with lifecycle scripts on):
  - npm packages missing or not at their locked versions: it stages its own install,
    `npm ci --include=dev --ignore-scripts` (lifecycle scripts off; no locked package
    declares one) in a directory under its state directory, checks every locked package is
    there, then swaps it in for `setup/node_modules`. The previous `node_modules` is kept
    until the re-check passes, and put back if it does not.
  - a missing browser: Playwright's own CLI from `setup/node_modules`
    (`install --no-remove chromium`, never `--with-deps`), which leaves `node_modules` alone.
  - missing Chromium libraries: unpacked without root (below).
- [uv](https://docs.astral.sh/uv/), for Python tests: the loop runs pytest as
  `uv run --no-project --with pytest==8.3.5 python -m pytest`, the version CI pins, which
  fetches pytest (and a Python, if none is found) into uv's cache.
- Network access for the engine itself. Under Codex, run it outside the default sandbox.

Check everything with:

```sh
scripts/implement.sh doctor           # toolchain, logins, ruleset, html tooling
scripts/implement.sh doctor --smoke   # plus one tiny structured call to each CLI (costs cents)
```

Run state lives under the git common dir (`.git/implementation-loop/`), worktrees in a sibling
`<repo>.loop/` directory. Agents run without your GitHub credentials. Per-role effort, models and
timeouts are in `tools/implementation-loop/loop.toml`.

### Browser libraries without root

When Chromium cannot start because Linux libraries are missing (`error while loading shared
libraries`) and nobody can run `sudo`, the loop repairs it in user space
([ADR 0011](../docs/adr/0011-autonomous-implement-loop.md), decision 5). By hand, on Debian
or Ubuntu, with the HTML browser tooling installed:

```sh
python3 setup/browser-libs.py --dest <dir> --dry-run   # list what it would fetch; writes nothing
python3 setup/browser-libs.py --dest <dir>
CURSUS_BROWSER_LIBS=<dir> node setup/doctor.mjs
```

- **What:** the packages Playwright 1.63.0 lists for Chromium on Ubuntu 24.04 and 26.04
  (pinned in the script, which cites the table they come from), plus any dependency apt's
  solver says the host lacks, never the C runtime. Versions are the ones in the host's apt
  indexes; `manifest.json` records each `.deb` and its SHA-256.
- **How it is verified:** `apt-get download` needs no root and checks each file against apt's
  signed indexes; `dpkg -x` unpacks them into a staging directory; then `ldd` on Playwright's
  Chromium executables, with the unpacked directories first on `LD_LIBRARY_PATH`, must report
  no missing library, and `setup/doctor.mjs`, given the staged copy, must launch Chromium and
  render offline HTML. Only then is the copy activated. A failure leaves the active copy as it
  was and exits non-zero. The loop launches Chromium again after activation; if it still
  fails, the loop rolls back.
- **Where:** only under `<dir>`: `libs-<content hash>/` (the unpacked files and
  `manifest.json`), a `current` file naming the active copy, and `previous` naming the copy it
  replaced, which is kept; older copies are deleted. The loop keeps its copy in its state
  directory under `.git/implementation-loop/`.
- **Who uses it:** nothing, unless `CURSUS_BROWSER_LIBS` names `<dir>` (or one copy in it).
  Then `tools/html-pages/browser.mjs` prepends the copy's library directories to
  `LD_LIBRARY_PATH` in the browser process's environment only, and names the browser
  executable so Playwright skips its own host check, which would run without them. No shell
  profile, `ld.so` configuration, Node process or other tool sees them.
- **Roll back:** `python3 setup/browser-libs.py --dest <dir> --rollback` undoes the last
  activation once: `current` goes back to the copy `previous` names (or to none, if no copy
  was active before), and the rolled-back copy is deleted.
- **Remove:** `rm -rf <dir>` and unset `CURSUS_BROWSER_LIBS`.
- **Limits:** Debian and Ubuntu only, and the apt indexes must be current (`apt-get update`
  needs root; stale indexes make downloads fail). A library no package provides still needs
  an administrator; the loop then parks only the work that needs a browser.

Skill wrappers and git hooks stay in their native discovery locations; this directory owns
their setup. Page authoring assets and checks live under `tools/html-pages/` and consume the
locked browser environment through `tools/html-pages/browser.mjs`.

## Repo administrators and fork owners: apply the rulesets

Prerequisites: Bash, GitHub CLI (`gh`) authenticated as a repository administrator, and `jq`.
Install those tools using your platform's package manager, and authenticate with `gh auth login`.
Then run once per repository or fork:

```sh
bash setup/apply-ruleset.sh
```

This creates or updates two GitHub rulesets, each matched by name:

- [`pr-only-main.json`](pr-only-main.json): PR-only changes to the default branch, a passing
  `required` CI check before merge (see
  [ADR 0007](../docs/adr/0007-required-ci-gate-and-merge-forward-shipping.md)), no force pushes,
  no deletion, and no bypass.
- [`homework-branches.json`](homework-branches.json): no force pushes and no deletion on every
  homework branch (`refs/heads/homework/**/*`, which reaches nested names such as
  `homework/s01/<handle>`), and no bypass (see
  [ADR 0009](../docs/adr/0009-homework-on-per-student-branches.md)).

Rulesets are server state, so cloning or forking alone does not apply them. Re-running the script
updates the matching rulesets; it fails if either one cannot be applied. It requires admin access
and is separate from local author setup. After the turn-in skill first lands, the owner's live
checks are in [`turn-in-owner-checks.md`](turn-in-owner-checks.md).

## Installation inventory

| Component | Source and destination |
| --- | --- |
| Git/Bash; Node/npm for HTML authors; gh/jq for administrators | Contributor-installed prerequisites; no global package manager changes are made by default |
| Repository skills and HTML assets | Checked-in `.claude/skills/`, `.agents/skills/`, and `tools/html-pages/`; no global skill installation |
| Git hooks | Checked-in `.githooks/`; `git-hooks.sh` configures the clone's `.git/config` |
| Implement loop | Checked-in `tools/implementation-loop/` (standard-library Python); run state under `.git/implementation-loop/`, worktrees in a sibling `<repo>.loop/` directory; uses the installed `claude`, `codex` and `gh` |
| Playwright, axe and transitive npm dependencies | Exact versions and integrity hashes in [`package-lock.json`](package-lock.json); installed in `setup/node_modules/`. The implement loop re-installs them only through a staging directory in its state directory under `.git/implementation-loop/`, with lifecycle scripts off |
| Chromium, headless shell and FFmpeg | Downloaded by the locked Playwright CLI into its per-user browser cache; `doctor.mjs` prints the executable location |
| Linux browser libraries | OS packages installed only with `--with-system-deps`; versions come from the supported distribution's repositories |
| Linux browser libraries without root | `browser-libs.py`: the pinned Chromium packages, plus dependencies apt says are missing, fetched with `apt-get download` and unpacked with `dpkg -x` under `--dest` only (the loop: its state directory under `.git/implementation-loop/`); used only by browser processes, through `CURSUS_BROWSER_LIBS` |
| Pinned pytest for the implement loop | `uv run --no-project --with pytest==8.3.5` fetches pytest, and a Python if needed, into uv's per-user cache |
| Session 1 toolchain and Python packages | `session-01-fundamentals.sh`: mise installs Python 3.12 and uv 0.11.28 (pinned in `sessions/01-fundamentals/mise.toml`) into mise's per-user directory; uv installs the PyPI packages pinned in `sessions/01-fundamentals/uv.lock` into `sessions/01-fundamentals/.venv/`. The `fixtures` group (torch, transformers) is installed only with `uv sync --group fixtures` |
| Git/Bash and an authenticated gh for students turning in homework | Contributor-installed prerequisites; `scripts/turn-in.sh` installs nothing |
| uv for the turn-in tests in CI | `astral-sh/setup-uv` installs uv 0.11.28 on the CI runner; `uv run --with pytest==8.3.5` fetches pytest into uv's cache |
| GitHub rulesets | [`pr-only-main.json`](pr-only-main.json) and [`homework-branches.json`](homework-branches.json); applied to the selected repository only when an administrator runs `apply-ruleset.sh` |
| MCP servers, third-party agent skills, global agent configuration | None installed or modified |

When adding another repository-wide tool, put its installer, manifests/lockfiles and diagnostic
entry points here, document its prerequisites and destinations in this inventory, and verify
the setup in a clean environment. Keep student-facing session runtime dependencies local to
their session, as required by [ADR 0001](../docs/adr/0001-self-contained-per-session-subfolders.md).
