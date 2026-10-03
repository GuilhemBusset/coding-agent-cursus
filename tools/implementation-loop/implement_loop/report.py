"""Text the engine shows: the plan, progress comments, the evidence comment and the PR body.

Each comment the engine owns carries an HTML marker, so it is updated in place, never duplicated.
"""

from __future__ import annotations

from .graph import Plan
from .model import Phase

PROGRESS_MARKER = "<!-- implement-loop:progress -->"
EVIDENCE_MARKER = "<!-- implement-loop:evidence -->"
RUN_MARKER = "<!-- implement-loop:run -->"

# Rough agent-call counts per issue size, used only for the plan's estimate.
CALLS_BY_SIZE = {"S": 8, "M": 14, "L": 18}


def render_plan(plan: Plan) -> str:
    lines = [f"Plan for #{plan.root} ({plan.mode} mode): {len(plan.work)} open work item(s)"]
    if plan.closed_work:
        lines.append(f"Already closed in the tree: {', '.join('#%d' % n for n in plan.closed_work)}")
    trackers = [n for n in plan.tracking if n != plan.root]
    if trackers:
        lines.append(f"Tracking issues: {', '.join('#%d' % n for n in trackers)}")
    lines.append("")
    by_wave: dict[int, list[int]] = {}
    for n in plan.work:
        by_wave.setdefault(plan.waves[n], []).append(n)
    for w in sorted(by_wave):
        lines.append(f"Wave {w}")
        for n in by_wave[w]:
            issue, spec = plan.issues[n], plan.specs[n]
            deps = ", ".join(f"#{d}" for d in sorted(plan.deps[n])) or "nothing"
            ext = " [external]" if n in plan.external else ""
            lines.append(f"  #{n} {issue.title}{ext}")
            lines.append(f"      size {issue.size} · {len(spec.ledger)} ledger items · branch {spec.branch or f'loop/issue-{n}'} · after {deps}")
    calls = sum(CALLS_BY_SIZE.get(plan.issues[n].size, 14) for n in plan.work)
    lines += ["", f"Estimate: about {calls} agent calls before fix rounds (rough; the first live run measures real cost)."]
    if plan.warnings:
        lines += ["", "Warnings:"] + [f"  - {w}" for w in plan.warnings]
    return "\n".join(lines)


PHASE_TEXT = {
    Phase.PENDING: "waiting for prerequisites",
    Phase.DESIGN: "designing",
    Phase.DESIGNED: "designed, waiting for a writer slot",
    Phase.CHECKS: "writing acceptance checks",
    Phase.IMPLEMENT: "implementing",
    Phase.VERIFY: "verifying",
    Phase.REVIEW: "in review",
    Phase.LAND: "landing",
    Phase.MERGED: "merged, verifying on main",
    Phase.ACCEPTED: "accepted; human evidence still needed",
    Phase.DONE: "done",
    Phase.NEEDS_HUMAN: "needs a human",
}


def render_progress(st, root: int) -> str:
    lines = [PROGRESS_MARKER, f"**implement loop** (run for #{root}): {PHASE_TEXT[st.phase]}", ""]
    rows = [("Branch", f"`{st.branch}`" if st.branch else "–"),
            ("Pull request", f"#{st.pr}" if st.pr else "–"),
            ("Implement attempts", str(st.attempts)),
            ("Fix rounds", str(st.fix_rounds)),
            ("Reviewed commit", f"`{st.reviewed_sha[:7]}`" if st.reviewed_sha else "–")]
    lines += ["| | |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows]
    if st.reason:
        lines += ["", f"**Why it stopped:** {st.reason}"]
    if st.human_tasks:
        lines += ["", "**Needs a person:**"] + [f"- [ ] {t}" for t in st.human_tasks]
    return "\n".join(lines)


def render_evidence(n: int, evidence: list[dict], head_sha: str, extra: list[dict] | None = None) -> str:
    lines = [EVIDENCE_MARKER, f"### Evidence for #{n} on `{head_sha[:12]}`", "",
             "| Criterion | Proof | Result | Detail |", "|---|---|---|---|"]
    for ev in evidence + (extra or []):
        proof = f"`{ev['command']}` in `{ev['cwd']}`" if ev.get("command") else ev.get("note", "")
        result = "pass" if ev["passed"] else "FAIL"
        detail = []
        if ev.get("exit_code") is not None:
            detail.append(f"exit {ev['exit_code']}")
        if ev.get("tests"):
            detail.append(", ".join(f"{k} {v}" for k, v in ev["tests"].items()))
        if ev.get("duration_s"):
            detail.append(f"{ev['duration_s']}s")
        lines.append(f"| {ev['criterion']} | {proof} | {result} | {'; '.join(detail)} |")
    tails = [ev for ev in evidence if ev.get("output_tail")]
    for ev in tails:
        lines += ["", f"<details><summary>{ev['criterion']} output (sha256 {ev['output_sha256'][:12]})</summary>", "",
                  "```", ev["output_tail"][-1500:].rstrip(), "```", "</details>"]
    lines += ["", "Recorded by the trusted verifier. Full reports and screenshots, if any, are CI artifacts (kept 7 days)."]
    return "\n".join(lines)


def render_pr_body(n: int, title: str, design: dict | None, advisory: list[dict], operator: str, other: str) -> str:
    lines = [f"Refs #{n}", "", f"Implements **{title}** through the implement loop.", ""]
    if design and design.get("decisions"):
        lines += ["## Design decisions"] + [f"- **{k}**: {v}" for k, v in design["decisions"].items()] + [""]
    lines += ["## Review",
              f"- Cross-vendor review by {other}, acceptance review by {operator}: no verified defects remain.",
              ]
    if advisory:
        lines += ["- Advisory notes (not blocking):"] + [f"  - {f['title']} ({f['reviewer']}, P{f['priority']})" for f in advisory[:10]]
    lines += ["", "The issue stays open until every ledger item has evidence; see the evidence comment below."]
    return "\n".join(lines)


def render_run_summary(root: int, phases: dict[int, Phase], reasons: dict[int, str], tasks: dict[int, list[str]]) -> str:
    lines = [RUN_MARKER, f"**implement loop**: run for #{root}", ""]
    counts: dict[str, int] = {}
    for ph in phases.values():
        counts[PHASE_TEXT[ph]] = counts.get(PHASE_TEXT[ph], 0) + 1
    lines += [f"- {v} × {k}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
    stuck = [n for n, ph in phases.items() if ph == Phase.NEEDS_HUMAN]
    if stuck:
        lines += ["", "**Needs a human:**"] + [f"- #{n}: {reasons.get(n, '')}" for n in stuck]
    open_tasks = [(n, t) for n, ts in tasks.items() for t in ts]
    if open_tasks:
        lines += ["", "**Evidence only a person can provide:**"] + [f"- [ ] #{n}: {t}" for n, t in open_tasks]
    return "\n".join(lines)
