"""The engine's rules for what blocks, what is allowed and what counts as progress (ADR 0012).

Pure functions, unit-tested: no git, no agents. They are part of the safety surface a
fault-repair run may never change.

- The issue text is the floor and the ceiling. A finding blocks only if it quotes at least three
  words of the item it says is violated (checked here, not trusted), or names a safety invariant
  from `loop.toml`, and carries a behavioural witness (observed against expected).
- An `owner` classification is valid only for a capability the host lacks; a `deferred` one
  only for an open issue whose title or body contains the quoted words.
- A round is productive when what fails changes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from .config import is_protected, is_safety_surface
from .model import AGENT_PROOFS, PROOF_KINDS, Finding

MIN_QUOTE_WORDS = 3
DEFAULT_INVARIANTS = (
    "secret exposure",
    "check or gate bypass",
    "data loss",
    "cross-run corruption",
    "wrong results presented as correct",
    "a false done",
    "edits to another issue's merged deliverable",
)


def normalize(text: str) -> str:
    """Lower case, markdown emphasis and code ticks removed, punctuation spaced out, one space."""
    text = (text or "").lower()
    text = re.sub(r"[`*_~]", "", text)
    text = re.sub(r"[“”\"'‘’]", "", text)
    text = re.sub(r"[^\w\s:/.#+=<>-]", " ", text)
    return " ".join(text.split())


def quote_ok(source: str, quote: str | None, min_words: int = MIN_QUOTE_WORDS) -> bool:
    """`quote` has at least `min_words` words and appears, normalized, in `source`."""
    q = normalize(quote or "")
    return len(q.split()) >= min_words and q in normalize(source)


def invariant_ok(name: str | None, invariants: tuple[str, ...] | list[str]) -> bool:
    n = normalize(name or "")
    return bool(n) and any(n == normalize(i) or normalize(i) in n for i in invariants)


# ------------------------------------------------------------------ plans

@dataclass
class OpenIssue:
    number: int
    state: str
    title: str
    body: str
    tracking: bool = False


def lint_plan(items: list[dict], ledger_ids: list[str], item_text: dict[str, str], lacks: list[str],
              lookup, zones: list[str]) -> list[str]:
    """Problems with a plan, each one actionable by the builder. `lookup(n)` returns an
    `OpenIssue` or None."""
    problems = []
    seen = [i["id"] for i in items]
    for missing in [i for i in ledger_ids if i not in seen]:
        problems.append(f"item {missing} has no plan entry")
    for extra in [i for i in seen if i not in ledger_ids]:
        problems.append(f"plan entry {extra} is not a ledger item")
    for i in items:
        if i["proof"] not in PROOF_KINDS:
            problems.append(f"{i['id']}: proof {i['proof']!r} is not one of {', '.join(PROOF_KINDS)}")
            continue
        if i["id"] in item_text and not quote_ok(item_text[i["id"]], i.get("quote"), 2):
            problems.append(f"{i['id']}: its reading must quote words of the item")
        if i["proof"] == "owner":
            if i.get("capability") not in lacks:
                problems.append(f"{i['id']}: `owner` needs a capability this host lacks ({', '.join(lacks) or 'none'}); "
                                f"{i.get('capability')!r} is not one of them, so agents must prove it")
            if not i.get("agent_part"):
                problems.append(f"{i['id']}: name the agent part (what agents still build and prove), or `none` with a reason")
        if i["proof"] == "deferred":
            other = lookup(i.get("depends_on")) if i.get("depends_on") else None
            if other is None or other.state != "open" or other.tracking:
                problems.append(f"{i['id']}: `deferred` needs an open, non-tracking issue; #{i.get('depends_on')} is not one")
            elif not quote_ok(other.title + "\n" + other.body, i.get("depends_quote"), 2):
                problems.append(f"{i['id']}: quote words of #{other.number}'s title or body that show the dependency")
    for z in zones:
        if z.startswith("/") or ".." in z.split("/"):
            problems.append(f"zone {z!r} must be a repo-relative path")
    return problems


def repair_plan(items: list[dict], ledger_ids: list[str], item_text: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """After one free retry, the engine makes the plan usable itself and publishes each change:
    a missing or unknown entry, or an invalid owner/deferred claim, becomes an agent item proven
    by review. Returns the items and the decisions."""
    fixed, decisions = [], []
    by_id = {i["id"]: i for i in items if i["id"] in ledger_ids}
    for item_id in ledger_ids:
        i = by_id.get(item_id)
        if i is None or i["proof"] not in PROOF_KINDS:
            decisions.append({"id": f"engine-{item_id}", "choice": f"{item_id} is proven by the examiner's review",
                              "rationale": "the plan gave it no usable proof"})
            i = {"id": item_id, "reading": item_text.get(item_id, ""), "quote": item_text.get(item_id, ""),
                 "proof": "review"}
        fixed.append(i)
    return fixed, decisions


def demote(item: dict, why: str) -> tuple[dict, dict]:
    """An invalid owner or deferred claim: the item stays the agents' to prove."""
    new = {**item, "proof": "review" if item.get("proof") in ("owner", "deferred") else item["proof"],
           "capability": None, "depends_on": None}
    return new, {"id": f"engine-{item['id']}", "choice": f"{item['id']} stays an agent item", "rationale": why}


def keep_objection(obj: dict, item_text: dict[str, str], lookup) -> bool:
    """Triage may only point out a misreading, a classification error or a dependency, each with
    a quote; a scenario list is kept for infra issues. Anything unquoted is dropped."""
    kind = obj.get("kind")
    if kind == "scenario":
        return True
    if kind in ("misreading", "classification"):
        return obj.get("item") in item_text and quote_ok(item_text[obj["item"]], obj.get("quote"))
    if kind == "dependency":
        other = lookup(obj.get("depends_on")) if obj.get("depends_on") else None
        return (obj.get("item") in item_text and quote_ok(item_text[obj["item"]], obj.get("quote"))
                and other is not None and quote_ok(other.title + "\n" + other.body, obj.get("depends_quote"), 2))
    return False


# ------------------------------------------------------------------ findings

UNCONDITIONAL_REPRO = re.compile(r"^\s*(false|exit\s+[1-9]\d*|/bin/false)\s*;?\s*$")


def classify(f: Finding, item_text: dict[str, str], invariants, reproduced: bool | None,
             agent_items: set[str], owner_items: set[str]) -> Finding:
    """Decide whether a finding blocks. `reproduced`: True when its reproduction fails on the
    exact head, False when it passes, None when it could not be run."""
    witness = bool((f.observed or "").strip()) and bool((f.expected or "").strip())
    tied_item = bool(f.item) and f.item in item_text and quote_ok(item_text[f.item], f.quote)
    tied_invariant = invariant_ok(f.invariant, invariants)
    if f.item in owner_items and not tied_invariant:
        f.status, f.blocking, f.reason = "advisory", False, "it concerns an owner part, which agents do not prove"
        return f
    if f.reproduction and UNCONDITIONAL_REPRO.match(f.reproduction):
        f.status, f.blocking, f.reason = "rejected", False, "its reproduction fails unconditionally"
        return f
    if reproduced is True:
        if (tied_item or tied_invariant) and witness:
            f.status, f.blocking = "open", True
            f.reason = (f"reproduced; it quotes {f.item}" if tied_item else f"reproduced; invariant: {f.invariant}")
        else:
            f.status, f.blocking = "follow_up", False
            f.reason = "reproduced, but tied to no quoted item or invariant (or no observed/expected witness)"
    elif reproduced is False:
        f.status, f.blocking, f.reason = "advisory", False, "its reproduction passes on this head"
    else:
        f.status, f.blocking, f.reason = "advisory", False, "no runnable reproduction"
    return f


def review_verdicts(verdicts: list[dict], item_text: dict[str, str], review_items: set[str]) -> tuple[dict, list[str], list[str]]:
    """The examiner's verdicts on review items: (accepted verdicts by item, unmet items that
    block, review items without a verdict)."""
    accepted, unmet = {}, []
    for v in verdicts:
        i = v.get("item")
        if i not in review_items:
            continue
        if v.get("verdict") == "met":
            accepted[i] = v
        elif v.get("verdict") == "unmet" and quote_ok(item_text.get(i, ""), v.get("quote")):
            accepted[i] = v
            unmet.append(i)
    missing = sorted(review_items - set(accepted))
    return accepted, sorted(set(unmet)), missing


# ------------------------------------------------------------------ zones

def path_allowed(path: str, grants: list[dict], test_files: list[str]) -> bool:
    from .scheduler import overlaps   # local import: scheduler imports config only
    return any(overlaps(path, g["path"]) for g in grants) or path in test_files


def zone_problems(changed: list[str], grants: list[dict], test_files: list[str], repair: bool) -> list[str]:
    """Changed files outside the issue's grants, protected paths without an approval, and (in a
    fault-repair run) anything on the safety surface."""
    problems = []
    outside = [f for f in changed if not path_allowed(f, grants, test_files)]
    if outside:
        problems.append(f"changed files outside the plan's zones and approved paths: {outside[:8]} "
                        f"(ask with a `paths` request if the issue needs them)")
    approved_protected = {g["path"] for g in grants if g.get("protected")}
    protected = [f for f in changed if is_protected(f) and f not in approved_protected
                 and not any(f.startswith(p.rstrip('/') + '/') for p in approved_protected)]
    if protected:
        problems.append(f"protected paths changed without approval: {protected[:8]} (ask with a `protected_change` request)")
    if repair:
        surface = [f for f in changed if is_safety_surface(f)]
        if surface:
            problems.append(f"a fault-repair run may not change the safety surface: {surface[:8]}")
    return problems


# ------------------------------------------------------------------ progress

def signature(problems: list[str], open_findings: list[str], unmet: list[str]) -> str:
    """What failed this round, independent of wording that changes every time (durations, shas)."""
    keys = sorted({re.sub(r"\d+(\.\d+)?\s*s\b|[0-9a-f]{7,40}", "", p.split(":")[0]) for p in problems})
    payload = json.dumps([keys, sorted(open_findings), sorted(unmet)])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def is_agent_proof(proof: str) -> bool:
    return proof in AGENT_PROOFS
