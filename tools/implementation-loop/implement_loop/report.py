"""Text the engine shows: the plan, progress comments, the evidence comment and the PR body.

Each comment the engine owns carries an HTML marker, so it is updated in place, never duplicated.
"""

from __future__ import annotations

from .graph import Plan
from .model import Phase

PROGRESS_MARKER = "<!-- implement-loop:progress -->"
EVIDENCE_MARKER = "<!-- implement-loop:evidence -->"
RUN_MARKER = "<!-- implement-loop:run -->"
FAULT_MARKER = "<!-- implement-loop:fault:{} -->"
BRIEFING_BODY_LIMIT = 6000

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


def render_briefing(plan: Plan) -> str:
    """What the explorers get: the plan and every work item's own text."""
    parts = [render_plan(plan)]
    for n in plan.work:
        body = plan.issues[n].body
        if len(body) > BRIEFING_BODY_LIMIT:
            body = body[:BRIEFING_BODY_LIMIT] + "\n[issue body truncated]"
        parts.append(f'<issue number="{n}" title="{plan.issues[n].title}">\n{body}\n</issue>')
    return "\n\n".join(parts)


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
    Phase.DELIVERED: "delivered; the owner must provide the remaining evidence",
    Phase.DONE: "done",
    Phase.PARKED: "parked",
}


def render_progress(st, root: int) -> str:
    lines = [PROGRESS_MARKER, f"**implement loop** (run for #{root}): {PHASE_TEXT[st.phase]}", ""]
    rows = [("Branch", f"`{st.branch}`" if st.branch else "–"),
            ("Pull request", f"#{st.pr}" if st.pr else "–"),
            ("Implement attempts", str(st.attempts)),
            ("Fix rounds", str(st.fix_rounds)),
            ("Reviewed commit", f"`{st.reviewed_sha[:7]}`" if st.reviewed_sha else "–")]
    lines += ["| | |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows]
    if st.phase == Phase.PARKED and st.reason:
        lines += ["", f"**Parked ({st.park_kind}):** {st.reason}", "",
                  f"_{PARK_HINT.get(st.park_kind, '')}_"]
    if st.human_tasks:
        lines += ["", "**For the owner** (tick the box in the issue once done; the loop closes it):"]
        lines += [f"- {t}" for t in st.human_tasks]
    return "\n".join(lines)


PARK_HINT = {
    "blocked": "Resumes on the next run once its prerequisite is no longer parked.",
    "environment": "Resumes on the next run once the host can run its checks (scripts/implement.sh doctor).",
    "transient": "Resumes on the next run.",
    "engine_error": "The fault is filed as a loop:engine-bug issue; resumes once the engine is updated.",
    "exhausted": "Every recovery step was tried. Edit the issue, or run scripts/implement.sh retry, to try again.",
}


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
    design = design or {}
    lines = [f"Refs #{n}", "", f"Implements **{title}** through the implement loop.", ""]
    log = design.get("decision_log") or [{"id": k, "choice": v, "rationale": ""} for k, v in (design.get("decisions") or {}).items()]
    if log:
        lines += ["## Decisions", "",
                  "Readings and choices the loop made on its own. To override one, edit the issue (reopen it "
                  "first if it is closed) and run the loop again.", ""]
        lines += [f"- **{d['id']}**: {d['choice']}" + (f" ({d['rationale']})" if d.get("rationale") else "") for d in log]
        lines.append("")
    manual = [c for c in design.get("checks", []) if c.get("kind") == "manual"]
    if manual:
        lines += ["## Left for the owner"] + [f"- {c['criterion']}: {c.get('description', '')}" for c in manual] + [""]
    lines += ["## Review",
              f"- Cross-vendor review by {other}, acceptance review by {operator}: no reproduced defects remain.",
              ]
    if advisory:
        lines += ["- Advisory notes (not blocking):"]
        lines += [f"  - {f['title']} ({f['reviewer']}, P{f['priority']}"
                  + (", could not be reproduced either way" if f.get("unresolved") else "") + ")" for f in advisory[:10]]
    lines += ["", "The issue closes when every ledger item has evidence; see the evidence comment below."]
    return "\n".join(lines)


def render_run_summary(root: int, states: dict) -> str:
    """The end-of-run report on the root issue: what is done, what waits for the owner, what is
    parked and why, and how many decisions the loop took on its own."""
    lines = [RUN_MARKER, f"**implement loop**: run for #{root}", ""]
    by_phase: dict[Phase, list[int]] = {}
    for n, st in states.items():
        by_phase.setdefault(st.phase, []).append(n)
    counts = [f"{len(ns)} {PHASE_TEXT[ph].split(';')[0]}" for ph, ns in sorted(by_phase.items(), key=lambda kv: -len(kv[1]))]
    lines.append(" · ".join(counts))
    done = by_phase.get(Phase.DONE, [])
    if done:
        lines += ["", "**Done:** " + ", ".join(f"#{n}" + (f" (PR #{states[n].pr})" if states[n].pr else "") for n in done)]
    decided = sum(len((st.design or {}).get("decision_log") or []) for st in states.values())
    if decided:
        lines += ["", f"**Decisions taken by the loop:** {decided}, listed in each pull request's Decisions section."]
    owner = [(n, t) for n in by_phase.get(Phase.DELIVERED, []) for t in states[n].human_tasks]
    if owner:
        lines += ["", "**Owner checklist** (tick the box in the issue itself; the next run closes it):"]
        lines += [f"- #{n} {t}" for n, t in owner]
    parked = by_phase.get(Phase.PARKED, [])
    if parked:
        lines += ["", "**Parked:**"] + [f"- #{n} ({states[n].park_kind}): {states[n].reason}" for n in parked]
    return "\n".join(lines)
