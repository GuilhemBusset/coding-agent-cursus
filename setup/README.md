# Repository setup

## Students: prepare your machine

**Start here if you take the course.** One command for your platform installs git, gh, uv, mise
and your agent, logs you in, clones the course and runs the setup check:
[`student/README.md`](student/README.md). It has a section per platform (Windows, WSL, macOS,
Debian and Ubuntu, Fedora, Arch, other Linux) with the command, what it installs and where, what
needs sudo or an administrator prompt, how to undo it, and how to read the script first.

The rest of this page is for maintainers and instructors.

This directory is the home for repository-wide installation scripts, dependency manifests,
diagnostics, and setup documentation. Run the commands below from the repository root.
Installation needs internet access; viewing generated HTML needs only a browser.

## Session 2: Python and Pi toolchain

Start with the existing [platform student installer](student/README.md). It supplies Git, mise
and uv; Session 2 adds no replacement installer. Linux prerequisites are the distribution's
Git and archive/download tools, macOS needs the Xcode Command Line Tools (the student installer
prompts), and native Windows uses Windows PowerShell 5.1 and the installer’s winget/Git steps.
Any OS package or administrator prompts belong to that documented installer; the Session 2
helper needs no administrator access. Download access to mise's Node/Python releases, PyPI and
the npm registry is required. No agent login or API key is required for Session 2 offline checks.

From a fresh clone, on Linux, macOS or native Windows:

```sh
uv run --no-project --python 3.12 python setup/session-02-research-agents.py
```

The helper uses shared `student/prepare.py` installation code: `mise trust mise.toml`,
`mise install`, `mise exec -- uv sync --locked`, `mise exec -- npm ci`, then the session's
Python offline check. The full student installer discovers this session automatically and also
runs locked npm installation. Download failures stop with a rerun command; shared preparation
retries transient download failures. Rerun the helper after lockfile changes. It replaces only
the generated environments, preserves student sources, branches and unrelated configuration,
and does not install global npm packages, write shell profiles or modify global Pi settings.

The session pins Node **24.15.0**, its bundled npm **11.12.1**, TypeScript **5.9.3**, and
`@earendil-works/pi-ai` / `@earendil-works/pi-agent-core` **1.5.2**. Package names and the
Node >=22.19.0 requirement were verified against the upstream
[pi-ai manifest](https://raw.githubusercontent.com/earendil-works/pi/main/packages/ai/package.json),
[agent-core manifest](https://raw.githubusercontent.com/earendil-works/pi/main/packages/agent/package.json)
and published npm metadata on 2026-11-14; imports and typing are tested against the locked release.
Python 3.12 and uv 0.11.28 follow the existing course tooling.

Mise installs runtimes in its per-user data directory (normally `~/.local/share/mise/installs/`
on Unix and `%LOCALAPPDATA%/mise/installs/` on Windows; `mise where node` prints the actual path).
Session locks/manifests stay in `sessions/02-research-agents/`; uv installs `.venv/` there and npm
installs `node_modules/` there. Downloads also populate their normal per-user caches; neither
cache is needed in an exported session. The reusable helper/editor workspace are repository
assets under `setup/`, and are not runtime dependencies of the copied session.

For a standalone session, copy the complete `sessions/02-research-agents/` folder and follow
its [README](../sessions/02-research-agents/README.md#standalone-session). The locked commands,
from that copied folder, are:

```sh
mise trust mise.toml
mise install
mise exec -- uv sync --locked
mise exec -- npm ci
mise exec -- npm run typecheck
mise exec -- npm test
mise exec -- uv run --locked python exercises/check_setup.py
```

To remove session packages, delete that session's `.venv/` and `node_modules/` in your file
manager; rerunning setup restores them. To remove the Node runtime too, run
`mise uninstall node@24.15.0` only after checking no other project uses it. Remove Python/uv
through mise only if unused elsewhere; see the student installer's removal instructions for
mise itself and OS packages. Student edits and runs are left alone.

### Session 2 platform evidence

The actual platform installer jobs in `.github/workflows/student-setup.yml` install twice;
`tests/student_setup/ci_verify.py` now additionally runs the Session 2 helper, offline check,
TypeScript typecheck and import test. A Linux typecheck of Windows branches is not a Windows run.
Local WSL2 Linux clean-install logs are produced during issue #178 validation. At implementation
handoff native Linux, macOS and native Windows execution are **unverified**, pending those CI jobs.

Owner: **Guilhem Busset**. For each unavailable platform (`platform:native-linux`, `platform:macos`, `platform:windows`),
retain a passing student-setup CI job log on the landing commit, or from a fresh clone on that
native OS run the helper above twice and all seven standalone commands above. Expect zero exits,
`Offline readiness: PASS`, a passing TypeScript import test and no changes to sources or unrelated
configuration on the second run. Record OS/runtime versions, both installation logs and the final
`git status --short`; until actual execution is recorded these are owner obligations, not passes.
No paid/live adapter evidence is claimed by this setup.

### Session 2: API credentials and adapter diagnostic

The supplied connection selects `gpt-5.4-mini-2026-03-17` through the OpenAI
Responses API. Use an authorized project **API key**, with separately configured
API billing and model access. [ChatGPT and API billing are separate](https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform);
a coding-agent subscription or login does not prove API compatibility. Do not put
credentials in source, a checked-in `.env`, command arguments, saved config or Pi's
global auth store. Set them only in the process environment. For example, in Bash
on Linux/macOS (private terminal; input is hidden):

```bash
read -rsp 'OpenAI API key: ' OPENAI_API_KEY
export OPENAI_API_KEY
```

In Windows PowerShell 5.1:

```powershell
$apiSecret = Read-Host 'OpenAI API key' -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', $apiSecret).Password
```

After setup, this command is free and deterministic on every student platform:

```sh
uv run --no-project --python 3.12 python setup/session-02-research-agents.py --adapter-smoke --offline
```

It starts and cleans up a local fake compatible Responses endpoint, selects it
through configuration/environment, and prints synthetic accounting for a tool
call, result continuation and deadline failure. No API key is required. To opt in
to **paid** API access, using the official OpenAI endpoint and selected snapshot:

```sh
uv run --no-project --python 3.12 python setup/session-02-research-agents.py --adapter-smoke --live
```

The smoke has no retries, at most three attempts, two 256-output-token turns and
a 5 ms timeout probe. It prints sanitized date/versions/settings, auth outcome,
tool/continuation outcome, trace, usage and estimated token cost. An incomplete
check exits nonzero. A timeout may still incur a charge with unknown usage.
Neither CI nor default checks invoke `--live`. Clear the key afterwards with
`unset OPENAI_API_KEY` in Bash or `Remove-Item Env:OPENAI_API_KEY` in PowerShell.

For application routing, `createAdapter(config)` accepts providers `openai` and
`openai-compatible`. An alias such as `workshop` resolves
`COURSE_ENDPOINT_WORKSHOP` from the environment (HTTPS, or loopback HTTP; no URL
userinfo/query/fragment). OpenAI's default alias `openai` uses its official `/v1`
base URL without an override. Compatible providers use `COURSE_API_KEY`; OpenAI
uses `OPENAI_API_KEY`. Keep URLs runtime-only and save aliases. Unsupported
protocols/settings fail before a request. The dedicated `--live` smoke always
uses the official OpenAI endpoint; `--offline` exercises the replaceable boundary.

[Adapter verification](../sessions/02-research-agents/adapter-verification.md)
records dated official sources, supported settings, prices and cost formula,
per-run/classroom spending controls, provider-limit caveats and the migration
checklist. It names **Guilhem Busset** as owner of the missing authorized live
evidence and exact rerun. Live compatibility remains **unverified** until that
evidence is recorded; the offline endpoint is not a live pass.

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

`npm --prefix setup test` runs `tools/html-pages/tests/run-all.mjs`, which lists the suite
folders (`tools/html-pages/tests/`, the page tooling's own suites, and each session's test parts,
`sessions/<NN>-*/tests/<part>/`, where its lessons' suites live) and passes every `*.test.mjs` file
in them to a single `node --test` (Node 22 or newer, the version CI uses). A new suite is collected
by adding the file; there is no list to register it in. Extra arguments go to `node --test` as
options, for example `npm --prefix setup test -- --test-reporter=tap`. To run one suite and reject
skipped or empty results, use `node tools/html-pages/tests/run-suite.mjs <path>/<name>.test.mjs`.

The tiny-lm suite also needs a C compiler on `PATH` as `cc` (OS-level; for example
`sudo apt-get install gcc` on Debian or Ubuntu, which GitHub's Ubuntu runners already have). It
compiles llama2.c's `run.c`, vendored at a pinned commit in
`sessions/01-fundamentals/cursus/labs/tiny-lm/reference/`, as the reference for the page's
logits. `node setup/doctor.mjs` reports the compiler and fails without it.

Check existing Cursus teaching pages with `npm --prefix setup run check-repo`. It runs
`check-page.mjs` on several pages at once, one per core but one and at most 8 (set
`CURSUS_CHECK_JOBS` to choose), and prints each page's report path as it finishes. CI runs this
same setup and test sequence on Linux, the only platform teaching pages need (ADR 0010).

## Session 1: set up the session

Prerequisites: [mise](https://mise.jdx.dev/getting-started.html), [uv](https://docs.astral.sh/uv/)
and Bash (Git Bash on Windows). The [student setup](student/README.md) installs all of them and
runs this step itself.

```sh
bash setup/session-01-fundamentals.sh
```

Run it from the repository root as above; from any other directory, pass the script's path
(for example `bash ../../setup/session-01-fundamentals.sh` from inside the session). It is a
wrapper over the student setup's shared step, [`student/prepare.py`](student/prepare.py): it
activates the git hooks, then in every session that has a `mise.toml`, a `pyproject.toml` and a
`uv.lock` (Session 1 included) runs `mise trust mise.toml`, `mise install` (the Python and uv
pinned in that session's `mise.toml`) and `mise exec -- uv sync --locked` (the runtime
dependencies and default `typecheck` group from its `uv.lock`). It also syncs the repository's
tools into `setup/.venv` and installs the pinned VS Code extensions when the
`code` CLI is available. It does not install the build-only `fixtures` group, and does
not run the setup check. Repeating it is safe. The session's own
[README](../sessions/01-fundamentals/README.md) covers running and validating it.

### Session 1: PowerShell and shellcheck for the pre-work tests

The pre-work setup check that students run (`sessions/01-fundamentals/exercises/check-setup.sh`
and `check-setup.ps1`) is tested through both entry points, so the session's test suite needs
PowerShell 7. On Linux:

```sh
bash setup/pwsh.sh
```

- **What:** PowerShell 7.6.6, the official `powershell-7.6.6-linux-x64.tar.gz` (or `-arm64`)
  from <https://github.com/PowerShell/PowerShell/releases/tag/v7.6.6>, checked against the
  pinned SHA-256 (`ddbc4a2d113bbd46d283cfedcbcd117a70caefd7673f41f2b4e0000badf103bc` for x64,
  `924829e54c983648f6f1419a2dc7f9433c861b2fb5bd57736ff096c24f133729` for arm64, from the
  release's `hashes.sha256`, checked 2026-10-10). A mismatch installs nothing.
- **Where:** unpacked into `~/.local/share/coding-agent-cursus/pwsh/7.6.6/`, linked as
  `~/.local/bin/pwsh`. No sudo, package manager or shell profile change. A PowerShell 7 or newer
  already on `PATH` is left alone. The tests look for `CURSUS_PWSH`, then `pwsh` or `powershell`
  on `PATH`, then `~/.local/bin/pwsh`.
- **Needs:** `curl`, `tar`, `sha256sum` or `shasum`, and the ICU library (`libicu`, from your
  distribution's packages). Without ICU, PowerShell does not start; install the package, or run
  it with `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1`.
- **Remove:** `rm -rf ~/.local/share/coding-agent-cursus/pwsh ~/.local/bin/pwsh`.

The Bash wrapper must also pass shellcheck, pinned through PyPI's `shellcheck-py` and fetched
into uv's cache, with nothing installed globally:

```sh
uv run --no-project --with shellcheck-py==0.10.0.1 shellcheck sessions/01-fundamentals/exercises/check-setup.sh
```

## Session test suites in CI

The required CI check runs the pytest suite of every session that has a `tests/` folder
(`.github/workflows/session-tests.yml`), on Linux: on every pull request that changes the session's
folder, `scripts/turn-in.sh` or the hooks, and on every push to `main` and nightly ([Validating a
change](#validating-a-change)). Each session runs in its
own pinned environment: `astral-sh/setup-uv` installs the uv version in the session's `mise.toml`,
then, from the session folder and with that file's Python version,

```sh
uv run --locked --group parallel pytest -q -m "not live" -n auto
```

installs the packages in its `uv.lock`, including its non-default `parallel` group
([pytest-xdist](https://pypi.org/project/pytest-xdist/), locked in `uv.lock`; `uv sync` does not
install it), and runs the same suite as the README's `uv run pytest`, spread over every core.
Then, also when the suite failed, `uv run --locked --group typecheck ty check` type-checks the
session, and the exercises once more as each platform ([Type checking](#type-checking)). Each
session's `pyproject.toml` must define both groups and a `[tool.ty]` table; the workflow stops
with an error if it does not. The run fails if it collects nothing or skips anything. A test that
needs what CI lacks (a
logged-in `claude` or `codex`, network access to a vendor API, credentials, a real laptop,
Windows or macOS) gets `@pytest.mark.live`, with the marker registered under `markers` in that
session's `[tool.pytest.ini_options]`, so CI deselects it; it never skips itself. No test needs
the marker yet, so no session registers it. Files that are not named `test_*.py`, such as
`tests/fixture_replay_checks.py`, are not collected, in CI or locally.

## Type checking

The repository's Python is type-checked with [ty](https://docs.astral.sh/ty/) (ADR 0014), in two
kinds of environment, each with its own exactly pinned ty:

- **The repository's own Python**: the implement loop engine, the check selector, the turn-in
  tests and `browser-libs.py`. The configuration is [`ty.toml`](../ty.toml) at the repository
  root; ty 0.0.95, and the pytest 8.3.5 it resolves the tests' imports against, are locked in
  [`pyproject.toml`](pyproject.toml) and [`uv.lock`](uv.lock) here. From the repository root,
  with uv installed:

  ```sh
  uv run --project setup --locked ty check
  ```

  The first run creates `setup/.venv/` (ignored by git) with the packages locked there and their
  dependencies, using a Python 3.11 or newer that uv finds or downloads; ty checks as Python 3.11
  on Linux whatever the interpreter. Remove it with `rm -rf setup/.venv`.
- **Each session's Python**: configured in the session's `pyproject.toml` (`[tool.ty]`, required:
  without it, ty walks up to the root `ty.toml` and checks the repository's code instead) and
  pinned in its `typecheck` dependency group, locked in its `uv.lock`. This is a uv default group:
  plain `uv sync --locked` installs ty into the session's `.venv/` and keeps it on later syncs.
  From the session folder: `uv run --locked ty check`. CI
  and `scripts/check-changed.sh` then check the exercises as each platform students use (ADR
  0010), which catches an API only one of them has:
  `... ty check --python-platform <linux|darwin|win32> exercises`.

Warnings fail like errors. ty also merges a user-level `~/.config/ty/ty.toml` if you have one,
and searches `$PYTHONPATH` before the tree's own folders, so a `PYTHONPATH` naming another
checkout makes it check this one against that one's modules (`scripts/check-changed.sh` runs
ty without it; by hand, `env -u PYTHONPATH ...`). CI has neither, so its result is the one that
counts. To bump ty, change the pin in
`setup/pyproject.toml` and in every session's `typecheck` group together (CI rejects a session
whose pin differs), relock each with the uv CI uses (0.11.28: `uv lock --project setup` from the
root, `uv lock` in each session folder), and fix what the new version reports in the same pull
request.

### VS Code

The student setup and session helper configure VS Code as part of installation. They sync the
locked Python environments, then run [`editor.py`](editor.py). If `code` (or `code-insiders`)
is on PATH, it installs and verifies the exact extension versions in [`editor.json`](editor.json):
Python, its Pylance/debugpy/Python Environments pack members, ty, Live Preview and Rainbow CSV.
Live Preview 0.4.20 requires VS Code 1.109 or newer. Pinning the pack members
prevents Python's automatic extension-pack installation from introducing unpinned tools. ty
provides language features; Pylance remains inactive in this workspace. The supported VS Code CLI
also routes installation to WSL when
invoked there with Remote - WSL installed. It changes no user settings. A failed extension
installation fails setup with a retry command. Without a VS Code CLI, setup explicitly reports
that editor installation was skipped; terminal work and other editors still work. On macOS,
VS Code's **Shell Command: Install 'code' command in PATH** enables this integration.

Open the course with `code setup/cursus.code-workspace`, or open a session folder on its own.
The checked-in workspace gives the repository and each session its own project: ty currently
uses one project per workspace folder, and the root `ty.toml` deliberately covers only repository
tooling. When adding a session, add it to [`cursus.code-workspace`](cursus.code-workspace).
Root-only folder mode covers repository tooling; use the course workspace for session checks.

The workspace and `.vscode/settings.json` files make ty the Python language server, with
completions, navigation and diagnostics from the same pinned executable as CI. Paths use
`${workspaceFolder}` and include Linux/macOS and Windows executable locations. Each project's
ty configuration binds its imports to its local environment (`setup/.venv` for the repository,
`.venv` for a session), independently of a previously selected editor interpreter. The Python
extension also defaults to that environment for running and debugging code.

Live Preview (`ms-vscode.live-server`) previews the HTML decks and teaching labs: open an HTML
file and choose **Show Preview** from its context menu. Rainbow CSV (`mechatroner.rainbow-csv`)
highlights CSV columns and shows their header on hover. Its virtual alignment is enabled in the
workspace and standalone folder settings, so columns line up without changing the file's bytes.
These recommendations and settings also travel with P00 exports.

VS Code's normal workspace trust prompt still applies: trust this checkout to use its configured
executable. An already open window may need **Developer: Reload Window** after setup. To rerun
only extension installation, run `uv run --no-project python setup/editor.py` from the repository
root. P00 exports carry their own settings and the same installer, so they work outside the
course checkout. Remove an extension with `code --uninstall-extension <id>`, using its ID from
`editor.json`. Deleting a project's `.venv` removes its Python tools.

References: [ty editor integration](https://docs.astral.sh/ty/editors/),
[ty editor settings](https://docs.astral.sh/ty/reference/editor-settings/),
[Live Preview](https://marketplace.visualstudio.com/items?itemName=ms-vscode.live-server),
[Rainbow CSV](https://marketplace.visualstudio.com/items?itemName=mechatroner.rainbow-csv),
[VS Code extension CLI](https://code.visualstudio.com/docs/configure/command-line#_working-with-extensions).

## Lint rules

The Python follows one set of Ruff rules: Ruff 0.17.3's default selection, less the few rules the
root [`ruff.toml`](../ruff.toml) ignores, with a reason for each family kept or dropped. Editors'
Ruff extension reads the same file, so the editor shows exactly these findings. From the
repository root, with the Ruff locked here (see [Import order](#import-order)), or the same version
through uvx:

```sh
uv run --project setup --locked ruff check .
uvx ruff@0.17.3 check .
```

Fix a finding in the code, or ignore it on its line with `# noqa: <rule> - <reason>`. Write
`check=False` on a `subprocess.run` whose failure the code handles itself, and `check=True` only
where a failure must stop the program. The P00 files that the recorded agent runs pin by SHA-256
take no edits: `ruff.toml` exempts them (`per-file-ignores`) from the rules that flag them. CI runs
only the import-order part of these rules (below); check the rest before pushing.

## Import order

Import blocks follow one order: Ruff's isort rules, with the settings in the root
[`ruff.toml`](../ruff.toml), which editors' Ruff extension reads too. Ruff 0.17.3 is locked beside
ty in [`pyproject.toml`](pyproject.toml) and [`uv.lock`](uv.lock) here, and installed into the same
`setup/.venv/`. From the repository root, check every file, or sort the ones you changed:

```sh
uv run --project setup --locked ruff check --select I .
uv run --project setup --locked ruff check --select I --fix <files>
```

CI's repo checks run the first command on every pull request, so an unsorted import anywhere in the
repository fails `required`; `scripts/check-changed.sh` runs it when a `.py` file, `ruff.toml` or
the lock changes. It runs from the root over the sessions' code too, so no session carries Ruff and
students' environment is unchanged. The P00 files that the recorded agent runs pin by SHA-256 are
exempt (`per-file-ignores` in `ruff.toml`).

`ruff.toml` sets `required-version` to the pinned version, so a Ruff of any other version, such as
the one an editor's Ruff extension bundles, refuses the configuration instead of reporting
differently. The checked-in VS Code settings (`.vscode/settings.json` and `cursus.code-workspace`)
set `ruff.path` to the Ruff in `setup/.venv`, so the Ruff extension runs the pinned version rather
than its bundled one; point any other editor's Ruff at the same executable. To bump Ruff, change
the pin in `setup/pyproject.toml` and `required-version` in `ruff.toml` together (a selector test
fails when they differ), relock with `uv lock --project setup` (uv 0.11.28, as CI), and fix what
the new version reports in the same pull request, leaving the exempt P00 files alone.

## Validating a change

`scripts/check-changed.sh` (Linux; Python 3.11 or newer, plus whatever the selected checks need
from the sections above) runs the checks a change can affect, and nothing else. The change is
everything since the merge base with `origin/main`: commits, staged, unstaged and untracked
files. `tools/test-impact/impact.py` maps it through
[`tools/test-impact/impact.toml`](../tools/test-impact/impact.toml) (ADR 0013).

```sh
scripts/check-changed.sh plan       # what would run, and why
scripts/check-changed.sh            # run it
scripts/check-changed.sh --base REF # measure the change against REF instead of origin/main
scripts/check-changed.sh --all      # run everything
```

| You changed | It runs | Local time, 24 cores |
| --- | --- | --- |
| one deck or teaching lab | `check-page.mjs` on the page, the browser suites that read it, the session's lesson tests (`tests/lessons`) | 10–15 s |
| a session's exercises | the session's lab tests (`tests/labs`) in parallel, and its type checks if Python changed | about 5 s |
| a session's lockfile, pins or README | both parts of the session's suite, and its type checks | about 10 s |
| `tools/implementation-loop/` | the engine tests, in parallel, and the repository's type check | about 10 s |
| `ty.toml` | the repository's type check | seconds |
| any `.py` file or `ruff.toml` | the import-order check, plus what else reads the file | seconds |
| `setup/pyproject.toml` or `setup/uv.lock` | the repository's type check and the import-order check | seconds |
| `scripts/turn-in.sh`, the hooks or a skill | the turn-in tests, `test-ship.sh` and the static repo checks, plus what reads them | seconds to a minute |
| a workflow, the selector, `setup/package*.json`, or a path the map does not know | everything | about a minute |

A session's suite has two parts, run separately (ADR 0017): `tests/lessons`, for what is taught
live (`cursus/`, `index.html`), and `tests/labs`, for what students run (`exercises/`). The map
gives each part the session paths it reads; a session file neither part claims runs both.

The rules err wide:
- a Node suite with no entry in the map runs on every change;
- a deleted or renamed file counts under its old path;
- a page is checked when it changes, when a file it loads changes, or when a file it links to is
  deleted or renamed.

The selected Node suites run three files at a time, as on one of CI's 4-vCPU shard runners;
`node --test`'s own default (one per core) overloads a larger machine past the suites' timeouts.

CI makes the same selection: on a pull request, ci.yml's `changes` job runs `impact.py github`
on the pull request's `BASE...HEAD`, and only the selected jobs, Node suites and pages run.
`required` accepts a skipped job only when `changes` succeeded and said the job does not apply.
Every push to `main`, the nightly run (03:17 UTC) and a manual dispatch run everything. A full run
that is not green opens the issue "CI: the full run on main is failing", or comments on it.

The selector's own tests: `uv run --no-project --with pytest==8.3.5 pytest -q tools/test-impact`.
When a test starts reading a file that its map entry does not name, add the file to the map.

## Claude Code and Codex

Use your installed, configured agent from the cloned repository. The repository supplies
`/html-page`, `/ship`, `/implement` and `/turn-in` through `.claude/skills/`, and `$html-page`,
`$ship`, `$implement` and `$turn-in` through `.agents/skills/`. No separate skill download or MCP
registration is needed.

### Instructors: the Session 1 Act III agent demos

[`sessions/01-fundamentals/cursus/demos/agent/`](../sessions/01-fundamentals/cursus/demos/agent/README.md)
(Linux only) drives both CLIs headless and needs nothing installed beyond the session setup above:

- **The context-bomb MCP server** is `context_bomb.py`, a standard-library script in that folder.
  It is passed per invocation only (`claude --strict-mcp-config --mcp-config <file>`,
  `codex exec -c mcp_servers.context_bomb.…`) and never registered with `claude mcp add` or
  `codex mcp add`. No global agent configuration changes.
- **To record**: Claude Code and Codex installed and logged in (`claude` then /login,
  `codex login`), and `tmux` for the Codex `/status` capture. The recordings were made with
  Claude Code 2.1.301 and codex-cli 0.162.1.
- **To reset offline**: the session's uv cache warmed once by the session setup (`uv sync`). The
  reset exports P00 to `<tempdir>/cursus-s1-agent/` and runs `uv sync --locked --offline` there.
- **To replay**: nothing; the replays start no CLI and open no socket.

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

For a Codex-operated run, that file pins `gpt-6.1-sol` for planning and initial implementation,
and `gpt-6-astra` for revisions and arbitration. Claude Code remains the independent examiner
using its configured default. Install and authenticate both CLIs as above; the Codex account
must have access to both models. These are runtime selections, not additional packages or
global configuration changes. Call records include the selected model and effort. The generic
`doctor --smoke` checks CLI access, not entitlement to every configured model; a model-access
error must be fixed in the account or in the checked-in role configuration before the run.
See the [role table and review standard](../tools/implementation-loop/README.md#review-standard).

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
| Student machine setup | `student/install.sh` (macOS, Linux, WSL) and `student/install.ps1` (Windows): git and gh from the platform's packages (apt with GitHub's apt repository, dnf with GitHub's rpm repository, pacman, winget, the Xcode Command Line Tools, Homebrew or gh's pinned, SHA-256-checked release archive under `~/.local/share/coding-agent-cursus/gh/`); uv and mise from their official installers at the versions in [`student/versions.env`](student/versions.env), and Claude Code and Codex from their official native installers, into the user's `~/.local/bin` (and on Windows the folders in [student/README.md](student/README.md)); the clone in `~/coding-agent-cursus`; then `student/prepare.py`. Tested by `tests/student_setup` and `.github/workflows/student-setup.yml` |
| Session 1 toolchain and Python packages | `session-01-fundamentals.sh`: mise installs Python 3.12 and uv 0.11.28 (pinned in `sessions/01-fundamentals/mise.toml`) into mise's per-user directory; uv installs the PyPI packages pinned in `sessions/01-fundamentals/uv.lock` into `sessions/01-fundamentals/.venv/`. The `fixtures` group (torch, transformers) is installed only with `uv sync --group fixtures` |
| PowerShell 7 for the Session 1 pre-work tests | `pwsh.sh`: the pinned, SHA-256-checked PowerShell 7.6.6 Linux tarball under `~/.local/share/coding-agent-cursus/pwsh/7.6.6/`, linked as `~/.local/bin/pwsh` |
| shellcheck for the pre-work check script | `uv run --no-project --with shellcheck-py==0.10.0.1` fetches the pinned shellcheck binary into uv's per-user cache |
| Git/Bash and an authenticated gh for students turning in homework | Contributor-installed prerequisites; `scripts/turn-in.sh` installs nothing |
| uv for the turn-in tests in CI | `astral-sh/setup-uv` installs uv 0.11.28 on the CI runner; `uv run --with pytest==8.3.5` fetches pytest into uv's cache |
| uv, Python and packages for the session test suites in CI | `astral-sh/setup-uv` installs the uv version pinned in each session's `mise.toml` on the CI runner; `uv run --locked` uses that file's Python version (the runner's, or one uv fetches into its cache) and installs the session's `uv.lock` packages into the session's `.venv/` |
| GitHub rulesets | [`pr-only-main.json`](pr-only-main.json) and [`homework-branches.json`](homework-branches.json); applied to the selected repository only when an administrator runs `apply-ruleset.sh` |
| Session 1 Act III agent demos | Checked-in `sessions/01-fundamentals/cursus/demos/agent/` (standard-library Python, including the context-bomb MCP server, passed per CLI invocation only); demo folders under `<tempdir>/cursus-s1-agent/`; uses the installed `claude`, `codex` and `tmux` |
| ty, and pytest for its import resolution, for the repository's own Python | `uv run --project setup --locked` installs the versions and hashes locked in [`uv.lock`](uv.lock) into `setup/.venv/`, using a Python 3.11 or newer that uv finds or downloads; configured by the root `ty.toml` |
| ty for each session's Python | The session's default `typecheck` dependency group, locked in its `uv.lock`; plain `uv sync --locked` installs it into the session's `.venv/` |
| VS Code extensions | `editor.py`, called by student/session setup, installs and verifies the exact Python, Pylance, debugpy, Python Environments, ty, Live Preview and Rainbow CSV releases in `editor.json` with the detected `code` CLI, into its local or remote extension host; checked-in `.vscode` settings and `cursus.code-workspace` select the locked project tools and visual CSV alignment; no user settings are written |
| Ruff, to lint and sort imports | `uv run --project setup --locked` installs the version and hashes locked in [`uv.lock`](uv.lock) into `setup/.venv/`, beside ty (`uvx ruff@0.17.3` fetches the same version into uv's per-user cache); configured by the root `ruff.toml`, whose `required-version` matches the pin |
| Change-based check selection | Checked-in `tools/test-impact/` (standard-library Python) and `scripts/check-changed.sh`; installs nothing, runs the checks above with their own tools |
| MCP servers, third-party agent skills, global agent configuration | None installed or modified |

When adding another repository-wide tool, put its installer, manifests/lockfiles and diagnostic
entry points here, document its prerequisites and destinations in this inventory, and verify
the setup in a clean environment. Keep student-facing session runtime dependencies local to
their session, as required by [ADR 0001](../docs/adr/0001-self-contained-per-session-subfolders.md).
