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
DEFERRED_MARKER = "<!-- implement-loop:deferred -->"
BRIEFING_BODY_LIMIT = 6000

# Rough agent-call counts per issue size, used only for the plan's estimate.
CALLS_BY_SIZE = {"S": 5, "M": 7, "L": 10}


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
    lines += ["", f"Estimate: about {calls} agent calls for a smooth run (each issue has a persistent call ceiling: S 20, M 30, L 45)."]
    if plan.warnings:
        lines += ["", "Warnings:"] + [f"  - {w}" for w in plan.warnings]
    lines += ["", "During the run the loop may, on its own:"]
    if plan.mode == "epic":
        lines.append("  - add open prerequisites from this epic discovered mid-run (each lands in its own PR, through "
                     "the same gates)")
    lines += ["  - turn an item into an owner obligation when it needs a capability this host lacks, or defer it to "
              "another open issue",
              "  - under the supervisor, file loop faults and run one repair per fault (never on the loop's safety "
              "surface), then resume"]
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
    Phase.PLAN: "planning",
    Phase.PLANNED: "planned, waiting for a writer slot",
    Phase.BUILD: "building",
    Phase.VERIFY: "verifying",
    Phase.EXAMINE: "examined by the other vendor",
    Phase.LAND: "landing",
    Phase.MERGED: "merged, verifying on main",
    Phase.DELIVERED: "delivered; obligations remain",
    Phase.DONE: "done",
    Phase.WAITING: "waiting",
    Phase.FAILED: "not delivered",
}

WAIT_HINT = {
    "merge_queue": "Another run is landing; this one lands next.",
    "claim": "Another run is working on this issue.",
    "ci": "The required check gave no verdict; the supervisor tries again.",
    "outage": "A vendor CLI could not reach its service; the supervisor resumes once it can.",
    "github": "GitHub kept failing; the supervisor tries again.",
    "environment": "The host cannot run the checks; the doctor's recipes repair it before the next run.",
    "engine": "An engine fault was filed as a loop:engine-bug issue; it resumes on a new engine version.",
    "run_ceiling": "The run's call ceiling stopped new calls; the next run continues.",
}


def render_progress(st, root: int) -> str:
    lines = [PROGRESS_MARKER, f"**implement loop** (run for #{root}): {PHASE_TEXT[st.phase]}", ""]
    rows = [("Branch", f"`{st.branch}`" if st.branch else "–"),
            ("Pull request", f"#{st.pr}" if st.pr else "–"),
            ("Agent calls", str(st.calls)),
            ("Open findings", str(sum(1 for f in st.findings if f.get("status") == "open"))),
            ("Certified commit", f"`{st.certified_sha[:7]}`" if st.certified_sha else "–")]
    lines += ["| | |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows]
    if st.phase == Phase.WAITING and st.wait:
        lines += ["", f"**Waiting ({st.wait.get('kind')}):** {st.wait.get('detail', '')}", "",
                  f"_{WAIT_HINT.get(st.wait.get('kind'), 'It resumes by itself.')}_"]
    if st.phase == Phase.FAILED and st.fail:
        lines += ["", f"**Not delivered ({st.fail.get('cause')}):** {st.fail.get('detail', '')}", "",
                  "_Filed as a loop fault. The branch keeps the work; a new engine version tries once more._"]
    if st.human_tasks:
        lines += ["", "**Remaining obligations** (owner items: tick the box in the issue once done; deferred items "
                      "reopen by themselves):"]
        lines += [f"- {t}" for t in st.human_tasks]
    return "\n".join(lines)


def render_evidence(n: int, evidence: list[dict], head_sha: str, verdicts: dict | None = None) -> str:
    lines = [EVIDENCE_MARKER, f"### Evidence for #{n} on `{head_sha[:12]}`", "",
             "| Criterion | Proof | Result | Detail |", "|---|---|---|---|"]
    for ev in evidence:
        proof = f"`{ev['command']}` in `{ev['cwd']}`" if ev.get("command") else ev.get("note", "")
        result = "pass" if ev["passed"] else "FAIL"
        detail = []
        if ev.get("exit_code") is not None:
            detail.append(f"exit {ev['exit_code']}")
        if ev.get("tests"):
            detail.append(", ".join(f"{k} {v}" for k, v in ev["tests"].items() if not isinstance(v, list)))
        if ev.get("duration_s"):
            detail.append(f"{ev['duration_s']}s")
        lines.append(f"| {ev['criterion']} | {proof} | {result} | {'; '.join(detail)} |")
    for item, v in sorted((verdicts or {}).items()):
        lines.append(f"| {item} | the other vendor's examination | {'pass' if v.get('verdict') == 'met' else 'FAIL'} | "
                     f"\"{(v.get('quote') or '')[:80]}\" on `{(v.get('head') or '')[:7]}` |")
    tails = [ev for ev in evidence if ev.get("output_tail")]
    for ev in tails:
        lines += ["", f"<details><summary>{ev['criterion']} output (sha256 {ev['output_sha256'][:12]})</summary>", "",
                  "```", ev["output_tail"][-1500:].rstrip(), "```", "</details>"]
    lines += ["", "Recorded by the trusted verifier. Full reports and screenshots, if any, are CI artifacts (kept 7 days)."]
    return "\n".join(lines)


def render_pr_body(n: int, title: str, st, operator: str, other: str) -> str:
    lines = [f"Refs #{n}", "", f"Implements **{title}** through the implement loop.", ""]
    if st.decisions:
        lines += ["## Decisions", "",
                  "Readings and choices the loop made on its own. To override one, edit the issue (reopen it "
                  "first if it is closed) and run the loop again.", ""]
        lines += [f"- **{d.get('id')}**: {d.get('choice')}" + (f" ({d['rationale']})" if d.get("rationale") else "")
                  for d in st.decisions]
        lines.append("")
    if st.obligations:
        lines += ["## Left for later"]
        for o in st.obligations:
            if o["kind"] == "deferred":
                lines.append(f"- {o['item']}: waits for {o['detail']}; it reopens by itself when that issue lands")
            else:
                lines.append(f"- {o['item']}: needs {o['detail']}, which the loop's host lacks"
                             + (f" (agents proved: {o['agent_part']})" if o.get("agent_part") not in (None, "none") else ""))
        lines.append("")
    follow = [f for f in st.findings if f.get("status") == "follow_up"]
    advisory = [f for f in st.findings if f.get("status") in ("advisory", "rejected")]
    lines += ["## Examination",
              f"- Built by {operator}; examined, probed and certified on this exact head by {other}. "
              f"No blocking finding remains."]
    if follow:
        lines += ["- Reproduced but not blocking (no ledger item or safety invariant requires them; filed as a "
                  "follow-up issue):"] + [f"  - {f['title']}" for f in follow[:10]]
    if advisory:
        lines += ["- Advisory notes:"] + [f"  - {f['title']} ({f.get('reason', '')})" for f in advisory[:10]]
    lines += ["", "The issue closes when every ledger item has evidence; see the evidence comment below."]
    return "\n".join(lines)


def render_run_summary(root: int, states: dict) -> str:
    """The end-of-run report on the root issue: what is done, what remains for the owner or waits
    for another issue, what is waiting and why, what failed, and how many decisions the loop took."""
    lines = [RUN_MARKER, f"**implement loop**: run for #{root}", ""]
    by_phase: dict[Phase, list[int]] = {}
    for n, st in states.items():
        by_phase.setdefault(st.phase, []).append(n)
    counts = [f"{len(ns)} {PHASE_TEXT[ph].split(';')[0]}" for ph, ns in sorted(by_phase.items(), key=lambda kv: -len(kv[1]))]
    lines.append(" · ".join(counts))
    done = by_phase.get(Phase.DONE, []) + by_phase.get(Phase.DELIVERED, [])
    if done:
        lines += ["", "**Merged:** " + ", ".join(f"#{n}" + (f" (PR #{states[n].pr})" if states[n].pr else "") for n in done)]
    decided = sum(len(st.decisions) for st in states.values())
    if decided:
        lines += ["", f"**Decisions taken by the loop:** {decided}, listed in each pull request's Decisions section."]
    owner = [(n, t) for n in by_phase.get(Phase.DELIVERED, []) for t in states[n].human_tasks]
    if owner:
        lines += ["", "**Remaining obligations** (owner items: tick the box in the issue itself; deferred items reopen "
                      "by themselves):"]
        lines += [f"- #{n} {t}" for n, t in owner]
    waiting = by_phase.get(Phase.WAITING, [])
    if waiting:
        lines += ["", "**Waiting** (resumes by itself):"] + [
            f"- #{n} ({(states[n].wait or {}).get('kind')}): {(states[n].wait or {}).get('detail', '')}" for n in waiting]
    failed = by_phase.get(Phase.FAILED, [])
    if failed:
        lines += ["", "**Not delivered** (filed as loop faults; a new engine version tries once more):"] + [
            f"- #{n} ({(states[n].fail or {}).get('cause')}): {(states[n].fail or {}).get('detail', '')}" for n in failed]
    follow = [(n, states[n].followup) for n in states if states[n].followup]
    if follow:
        lines += ["", "**Follow-up issues:** " + ", ".join(f"#{f} (from #{n})" for n, f in follow)]
    return "\n".join(lines)
