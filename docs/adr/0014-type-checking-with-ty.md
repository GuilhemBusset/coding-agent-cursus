# ADR 0014 — Type-check the repository's Python with ty

- **Status:** Accepted
- **Date:** 2026-11-04
- **Deciders:** Guilhem Busset (instructor / repo owner)
- **Context:** [ADR 0001](0001-self-contained-per-session-subfolders.md), [ADR 0010](0010-platform-support.md), [ADR 0013](0013-test-tiers-and-selection.md)

## Context

The repository's Python carried annotations that nothing checked: the implement loop engine, the
check selector, the turn-in tests, `setup/browser-libs.py`, and each session's labs, demos,
exercises and tests. Run for the first time, a type checker found about 280 diagnostics. Most
were real gaps between the annotations and the code: steps annotated `-> None` that returned a value,
`str | None` fields used as `str` where a phase guarantees them, a parameter reused for a value
of another type, `Popen` streams used without checking that they exist. About 50 more were
imports a checker could not resolve because nothing declared where each program's imports start.

Two constraints shape where a checker runs:

- **Two kinds of environment.** Each session is self-contained (ADR 0001): its own `pyproject.toml`,
  `uv.lock` and `.venv`, with its own third-party packages, and its `pyproject.toml` is copied
  byte for byte into the P00 export students receive. The repository's own tooling is
  standard-library Python run with a pinned pytest through `uv run --with`, which installs into an
  overlay that ty does not read (uv's `.pth` file holds an `import` line, which ty ignores), so ty
  could not resolve `pytest`.
- **Platforms.** Exercises run on Linux, macOS and Windows; everything else only on Linux (ADR
  0010).

## Decision

1. **ty, pinned exactly.** [ty](https://docs.astral.sh/ty/) is Astral's checker, from the makers
   of the uv the repository already uses. It is still 0.0.x, and its diagnostics change between
   releases, so every pin is exact (`ty==0.0.95`), never a range. A version bump is a change of
   its own, with the diagnostics it brings fixed in the same pull request.
2. **The repository's own Python** is checked from the root with `ty.toml`: the engine, the
   selector, `tests/turn_in/` and `setup/browser-libs.py`, as Python 3.11 (the oldest the engine
   and the selector support) on Linux. Loose probe and examiner scripts that nothing runs
   (`impact.toml`'s `[none]`) are not checked. ty and the pytest it resolves come from a locked
   environment, `setup/pyproject.toml` and `setup/uv.lock`, run with
   `uv run --project setup --locked ty check`.
3. **Each session checks itself**, from its folder, with its `pyproject.toml`'s `[tool.ty]` and
   ty from a default `typecheck` dependency group, locked in its `uv.lock`:
   `uv run --locked ty check`. Plain `uv sync` installs and retains the editor's checker
   (updated by [ADR 0016](0016-reproducible-python-editor-setup.md)). Only
   the configuration's excludes name paths that exist only in the session, and an exclude that
   matches nothing is ignored, so ty also works in the P00 export. `python-platform = "all"`
   checks every platform's branches instead of treating the Windows and macOS ones as unreachable
   on Linux. It also accepts an API that only one platform has, so CI checks `exercises/` once more
   as each of `linux`, `darwin` and `win32`. The opt-in `fixtures` group's torch and
   transformers, which neither CI nor `uv sync` installs, are allowed to stay unresolved.
4. **Warnings fail** like errors (`error-on-warning`), so an unused ignore fails too. A
   `# ty: ignore[<rule>]` names its rule and says why beside it. It is kept for code that steps
   outside its annotations on purpose (a test double replacing a method) or that ty misreads (a
   sibling import in a PEP 723 script).
5. **In the gate.** CI's repo checks run the root check on every pull request (seconds), and each
   session's job runs its checks after its pytest suite, also when the suite failed. A session
   without a `[tool.ty]` table fails that job: ty would otherwise walk up to the root `ty.toml`
   and check the repository's code instead. `impact.toml`'s `typecheck` unit selects the root
   check locally (`scripts/check-changed.sh`); a session's checks run with its suite.

## Consequences

- A type error in checked code fails `required`. Fixing the first run's diagnostics changed no
  behavior on valid inputs: annotations were corrected, and invariants each phase already relied
  on became `assert`s, which fail at the line that assumed them instead of further on.
- The pytest pin gains one more copy, in `setup/pyproject.toml`, where ty only reads it beside
  the `uv run --with pytest==8.3.5` commands. A pytest bump changes it too.
- The ty pin appears once per environment (`setup/pyproject.toml` and each session's
  `pyproject.toml`). A bump changes them together; CI rejects a session whose pin differs. ty is
  instructor tooling, not taught material, so ADR 0001's freedom for sessions to use different
  tool versions does not extend to it.
- Editors that run ty's language server pick up the same configuration: `ty.toml` at the root,
  `[tool.ty]` in a session opened as its own workspace folder. Each configuration binds imports
  to its project's environment. The course workspace includes both the repository and sessions;
  opening only the repository root does not apply nested session projects (ADR 0016).
- ty merges a user-level configuration (`~/.config/ty/ty.toml`) into every run, so a local result
  can differ from CI's, which has none.

## Alternatives considered

1. **mypy or pyright.** Both are more mature, and either would have worked. ty was asked for; it
   comes from the makers of uv, installs as one binary wheel per platform, and checks the
   repository's own Python in a second or two, which lets it run on every pull request.
2. **One root configuration for everything.** ty reads one configuration per project and one
   Python environment, so session code would be checked without its packages; it would also tie
   sessions to the root, against ADR 0001.
3. **`uv run --with ty==…`, like pytest.** At the root, ty cannot see packages installed that way
   (above). In a session it can (uv's overlay names the session's `.venv` in its `pyvenv.cfg`, and
   ty follows it), but ty's version would then live on every command line instead of being locked
   with its hashes in `uv.lock`.
4. **Allowing `pytest` to stay unresolved.** It would hide every mistake in how tests use it.
