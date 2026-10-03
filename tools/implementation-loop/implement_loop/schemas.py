"""JSON schemas for every agent answer.

They are written in the strict form both vendors accept: every property required (optional
values are nullable), no extra properties, no numeric bounds. Claude Code gets them through
`--json-schema`, Codex through `--output-schema`.
"""

from __future__ import annotations


def obj(**props) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def arr(items: dict) -> dict:
    return {"type": "array", "items": items}


STR = {"type": "string"}
NSTR = {"type": ["string", "null"]}
BOOL = {"type": "boolean"}
NUM = {"type": "number"}
INT = {"type": "integer"}
NINT = {"type": ["integer", "null"]}

CHECK = obj(
    criterion=STR,
    kind={"type": "string", "enum": ["command", "artifact", "manual"]},
    command=NSTR,
    cwd=STR,
    description=STR,
)
DECISION = obj(id=STR, choice=STR, rationale=STR)

EXPLORE = obj(notes=STR)
PROPOSAL = obj(
    decisions=arr(DECISION),
    checks=arr(CHECK),
    files=arr(STR),
    check_files=arr(STR),
    open_questions=arr(STR),
)
OBJECTIONS = obj(objections=arr(obj(text=STR, blocking=BOOL, changes_criterion=BOOL)))
DESIGN = obj(
    decisions=arr(DECISION),
    checks=arr(CHECK),
    files=arr(STR),
    check_files=arr(STR),
    notes=STR,
    criterion_disputes=arr(STR),
)
CHECKS_WRITTEN = obj(files_written=arr(STR), note=STR)
IMPLEMENTED = obj(status={"type": "string", "enum": ["done", "impossible"]}, note=STR)
REVIEW = obj(
    findings=arr(obj(
        id=STR, priority=INT, confidence=NUM, title=STR, file=NSTR, line=NINT,
        reproduction=NSTR, criterion=NSTR, claims_acceptance_failure=BOOL,
    )),
    coverage=arr(obj(criterion=STR, met=BOOL)),
    summary=STR,
)
VERDICT = obj(reproduced=BOOL, evidence=STR)

BY_ROLE = {
    "explore": EXPLORE,
    "propose": PROPOSAL,
    "audit": OBJECTIONS,
    "critique": OBJECTIONS,
    "judge": DESIGN,
    "write_checks": CHECKS_WRITTEN,
    "implement": IMPLEMENTED,
    "review": REVIEW,
    "verify_finding": VERDICT,
}


def validate(value, schema: dict, path: str = "$") -> list[str]:
    """A small structural validator for the subset of JSON Schema used above."""
    errors: list[str] = []
    types = schema.get("type")
    allowed = types if isinstance(types, list) else [types]
    kinds = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
    ok = False
    for t in allowed:
        if t in ("integer", "number"):
            ok |= isinstance(value, (int, float)) and not isinstance(value, bool) and (t == "number" or float(value).is_integer())
        elif t in kinds:
            ok |= isinstance(value, kinds[t])
    if not ok:
        return [f"{path}: expected {types}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, dict) and "properties" in schema:
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: missing")
        for key, sub in schema["properties"].items():
            if key in value:
                errors += validate(value[key], sub, f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors += validate(item, schema["items"], f"{path}[{i}]")
    return errors
