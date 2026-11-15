# Session 2 · Build, compare, submit

Open [home.html](home.html) directly from disk for the homework brief. Everything here is
public: cases, references, variants, rubric, fault schedules and completed solutions.
Build the same single-agent Pi program first; improve its harness with prompts held fixed,
then freeze code and compare prompts. No Session 1 or sibling inference repository is used.

## Install and export

From a course clone, follow [repository setup](../../../setup/README.md#session-2-python-and-pi-toolchain)
and run `uv run --no-project --python 3.12 python setup/session-02-research-agents.py` from its root.
Run the helper twice to check rerun behaviour. Thereafter, commands below run from the session
folder (`sessions/02-research-agents`), with its pinned runtimes on PATH (`mise exec --` can
prefix each command). Python 3.12, uv 0.11.28, Node 24.15.0 and npm 11.12.1 are the local pins.

Export into a new directory outside this session:

```sh
uv run --locked python -m exercises.fixed.export --output "../session-02 standalone"
```

The export carries session manifests/locks, editor settings, tests, teaching pages, public
cases/references/variants, fixed support, pinned offline rating ZIP, every checkpoint and
worked experiment version, plus your editable harness/prompts. It omits installed environments,
`.env` files, caches and all private runs. In the exported folder, with mise and uv installed:

```sh
mise trust mise.toml
mise install
mise exec -- uv sync --locked
mise exec -- npm ci
mise exec -- npm run typecheck
mise exec -- npm test
mise exec -- uv run --locked python exercises/check_setup.py
```

These are the same commands on Linux, macOS and Windows. Downloads occur during installation;
subsequent exercises below need no network, root package, account or API key. Environments live
in `.venv/` and `node_modules/`; remove those folders to uninstall local packages. Repository-wide
installers stay under `setup/` and are not needed by an installed export. To submit from an
export, copy your listed submission artifacts back into a fresh course clone: shared turn-in
belongs to that clone, not to the export.

## Inspect and rejoin offline

```sh
uv run --locked node exercises/fixed/bridge/inspect.ts --case exercises/cases/c-audit
uv run --locked python -m exercises.fixed.checkpoint rejoin 04-audit-stop
uv run --locked python -m exercises.fixed.checkpoint run 04-audit-stop --case c-audit --offline --name completed-c
uv run --locked python -m exercises.fixed.replay --run exercises/fixed/fixtures/faults/transient-read --out exercises/runs/replay-read
uv run --locked python -m exercises.fixed.evaluate compare --experiment exercises/fixed/examples/prompt.json --output exercises/runs/practice-comparison
```

Choose new output names on reruns. Rejoin preserves previous editable directories in
`runs/backups/`. The checkpoint run grades automatically; its report, claims, trace, accounting,
scorecard and peer checklist are adjacent. A comparison exit 1 means quality/retention gates
failed; inspect its output. Exit 2 means invalid inputs. Neither is a live compatibility result.
The supplied scripted answers can fail on public variants; preserve that truthful failure.

Public solutions: [00 model](fixed/checkpoints/00-model/README.md),
[01 read](fixed/checkpoints/01-read/README.md), [02 search](fixed/checkpoints/02-search/README.md),
[03 memory](fixed/checkpoints/03-memory/README.md), [04 numbers/recovery/stopping](fixed/checkpoints/04-audit-stop/README.md).
Each guide links its completed harness and prompt. [Worked experiments](fixed/examples/README.md)
include saved harness/prompt variants and scripts. Case answers are in
[A reference](cases/a-find/reference.json), [B reference](cases/b-compare/reference.json),
[C reference](cases/c-audit/reference.json), and each public variant's `reference.json` under
`cases/<case>/variants/`. The [public manifest](fixed/config/public/manifest.json) lists every
variant, seed, class/submission slot and [fault solution](fixed/config/public/README.md).

## Two controlled comparisons

1. Save a baseline with `uv run --locked python -m exercises.fixed.snapshot --name h-before`.
   Make **one harness improvement** in `harness/` (for example retained evidence or stopping),
   hold prompts fixed, and save `h-after`. Explain the hypothesis in [home-notes.md](home-notes.md).
2. Configure the comparison, using saved versions rather than mutable working files:

```sh
uv run --locked python -m exercises.fixed.examples.workflow configure harness --baseline exercises/runs/versions/h-before --candidate exercises/runs/versions/h-after --output exercises/runs/harness-experiment.json
```

3. Open that JSON in your editor. Set `mode` to `submission`. Keep the public `settings` and
   `rating_export`. With an authorized API budget and environment-only credentials, remove
   `scripts` and add `--live` to the compare command below. For an outage/offline attempt retain
   `scripts`, omit `--live`, record the outage and label results synthetic. Never label scripted
   answers or replay as captured live. Provider/endpoint remain configurable in the adapter for
   development; submission comparisons use the common public configuration.

```sh
uv run --locked python -m exercises.fixed.evaluate compare --experiment exercises/runs/harness-experiment.json --output exercises/runs/submission/harness
```

4. Inspect `comparison.md`, per-case before/after results and every failed attempt. Adopt or
   revert based on quality first, then measured tokens per success; failed calls/retries count.
   Save a prompt baseline `p-before` with the chosen harness, edit only `prompts/`, and save
   `p-after`. Configure `prompt` in the same way, change its mode to `submission`, and run into
   `exercises/runs/submission/prompt`. Freeze harness code in both prompt versions.
5. Both comparisons use **three trials per A/B/C per version** (18 attempts each), identical
   public variants/seeds, model/settings/tools/budgets/rating support and fresh workspaces.
   Class mode uses only one announced variant/trial per case. Do not substitute class results,
   drop failed trials or mix configurations. Run names and destinations are immutable; move
   an old submission aside before rerunning a complete comparison.

The public [rubric](fixed/config/policy.v1.json) requires every decisive requirement, at least
80% required facts, valid support for every factual claim, no unsupported decision and no
intervention. Caps (12 model attempts, 20 tools, 30,000 tokens) and gates are provisional pending
pilot calibration. Earlier cases must remain correct before efficiency matters. Zero successes
has no finite tokens-per-success score; missing usage stays unknown. Machine quality does not
establish prose entailment or live autonomy.

## Peer audit, outage status and gate

Follow every attempt's `peer-review.md`: compare each anchored report sentence with its typed
claim and actual source passage/CSV rows. Record unsupported wording, corrected scope and
uncertainty, not merely matching IDs. Write reviewer/date, inspected attempts, findings and
pending items in `runs/submission/peer-audit.md`; explicitly write `pending` if no peer is
available. Complete `home-notes.md`, including your adoption decision and live/outage status.

After the audit, seal the completed artifact set and run the same gate as turn-in:

```sh
uv run --locked python -m exercises.fixed.turn_in_check --seal --live-status unavailable
bash exercises/turn-in-check.sh
```

Use `--live-status available` only when real captured-live attempts exist; the structural gate
still reports `live_verification: unverified` and `live_pass: false`. Independent authorized
live verification and human review are separate evidence. Synthetic, replay-only and
unavailable-live evidence never become a live pass. Replay supports diagnosis; for a complete
outage submission run the two synthetic comparisons above and retain their failing grades.

Malformed, incomplete, hash-inconsistent or secret-bearing artifacts are rejected. Complete,
truthful low-quality attempts **may be submitted with a failing quality score**. The gate never
calls a model, never repairs submitted scores, and compares temporary regrades against pinned
support. `--seal` cannot legitimize changed schedules, forged scores or incompatible controls.
After any legitimate audit edit, reseal. Credentials belong only in your environment: never in
prompts, source, notes, traces or `.env` files in the submission.

## Turn in from the course clone

Use `/turn-in 02` in Claude Code, `$turn-in 02` in Codex, or from the repository root:

```sh
bash scripts/turn-in.sh 02
```

Windows uses **Git Bash** for this inherited wrapper; Python exercise commands work natively.
Authenticate `gh` first. The existing script runs the gate, commits only this session's
`exercises/`, and appends a new commit to public `homework/s02/<handle>`. Without course push
access it uses your fork and prints a compare URL. Retain each submission's history; never
rewrite, delete or merge these homework branches. Other staged/unstaged work stays untouched.
A refusal must be fixed before retrying; never bypass the gate.

Git submits tracked supplied `fixed/`, `cases/`, homework HTML/instructions and the gate, plus
your `harness/`, `prompts/`, `home-notes.md` and **all of `runs/submission/`**: both comparisons'
versions, experiment/settings/shared/public manifests, pinned cache, scripts (if synthetic), all
scheduled attempt inputs/configs/reports/claims/traces/dispatches/reservations/accounting/scores,
peer checklists, before/after/comparison outputs, `peer-audit.md` and `submission.json` hashes.
Other generated `runs/` content (practice, backups, loose versions and private runs) stays ignored.
Do not force-add it. Review `git status --short -- sessions/02-research-agents/exercises/`
from the root before submitting. Never include credentials or real student work in test fixtures.
