# Session 2 — Research agents

This independently runnable session follows the [locked 120-minute plan](https://github.com/GuilhemBusset/coding-agent-cursus/blob/855763fa7e51fdef4c4e4edf976315f1d3b829c5/docs/session-02/README.md):
build one single-agent Pi program first, experiment with its harness, then freeze code and
experiment with prompts. This scaffold establishes the toolchain; the research workflow,
contracts, public cases, checkpoints and teaching pages arrive in the subsequent issues.

## Install from a course clone

Follow the existing [student installer](../../setup/student/README.md) for your OS, then from
the repository root run the Session 2 helper (Linux, macOS, native Windows):

```sh
uv run --no-project --python 3.12 python setup/session-02-research-agents.py
```

See [Session 2 setup](../../setup/README.md#session-2-python-and-pi-toolchain) for prerequisites,
OS steps, installation locations, reruns, removal and platform evidence obligations. No
Session 1 environment or runtime import is needed.

## Standalone session

Copy this whole folder, including its hidden editor settings and locks, anywhere (spaces in
paths are supported). With mise and uv installed as documented under setup/, open a terminal
in this folder and run these commands on all three operating systems:

```sh
mise trust mise.toml
mise install
mise exec -- uv sync --locked
mise exec -- npm ci
mise exec -- npm run typecheck
mise exec -- npm test
mise exec -- uv run --locked python exercises/check_setup.py
```

If the pinned Node/npm and Python are already on PATH, the commands after `mise exec --` can
also be run directly. Installation downloads packages. Typechecking, tests and the setup check
run offline, require no API key, and make no paid model calls. `Offline readiness: PASS` means
the local toolchain and Pi imports work. It does **not** certify the separately authorized live
adapter smoke test, endpoint compatibility, model selection or classroom readiness.

Run Python exercise tests and typing from this folder:

```sh
mise exec -- uv run --locked --group parallel pytest tests/labs
mise exec -- uv run --locked ty check
```

`test_setup.py` also runs the TypeScript typecheck and `pi-setup.test.ts` import smoke, so the
same entry point is selected locally by `scripts/check-changed.sh` and in session CI. Repository
setup/layout tests run from the root with
`uv run --project setup --locked pytest tests/student_setup tests/sessions`.

## Ownership and layout

Session-local `mise.toml`, `pyproject.toml`, `uv.lock`, `package.json`, `package-lock.json` and
`tsconfig.json` define the runtime. Python installs in `.venv/`; npm installs in `node_modules/`.
The runtime uses no root package, Session 1 code, global npm packages, or global Pi configuration.
Python remains light; parallel test workers are opt-in, and ty is installed by default.

- `cursus/`: supplied lesson material.
- `exercises/harness/` and `exercises/prompts/`: student edits.
- `exercises/fixed/`: supplied tools, evaluation support and completed checkpoints.
- `exercises/cases/<case>/`: public cases and their `reference.json` (added with the cases).
- `exercises/runs/`: generated outputs, ignored by git.
- `tests/labs/`: offline exercise/toolchain checks; later lesson tests go in `tests/lessons/`.

Repository-wide installers, diagnostics, the editor workspace and their installation instructions
live under `setup/`. Open `setup/cursus.code-workspace` for the course, or this folder alone in
VS Code for the standalone session. The session selects its local Python environment and local
TypeScript compiler. Credentials belong only in the environment at the future adapter boundary;
do not save keys in source, configuration, output or traces.
