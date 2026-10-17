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

DECISION = obj(id=STR, choice=STR, rationale=STR)
EXPLORE = obj(notes=STR)
SMOKE = obj(ok=BOOL)

PROOF = {"type": "string", "enum": ["test", "command", "review", "owner", "deferred"]}
ITEM_PLAN = obj(id=STR, reading=STR, quote=STR, proof=PROOF, capability=NSTR, agent_part=NSTR,
                depends_on=NINT, depends_quote=NSTR)
PLAN = obj(items=arr(ITEM_PLAN), zones=arr(STR), decisions=arr(DECISION), notes=STR)
TRIAGE = obj(objections=arr(obj(
    kind={"type": "string", "enum": ["misreading", "classification", "dependency", "scenario"]},
    text=STR, item=NSTR, quote=NSTR, proof={"type": ["string", "null"]}, capability=NSTR,
    depends_on=NINT, depends_quote=NSTR,
)))
COMMAND = obj(criterion=STR, command=STR, cwd=STR, timeout_s=NINT)
REQUEST = obj(
    kind={"type": "string", "enum": ["paths", "protected_change", "command_change", "test_change", "reclassify",
                                     "depends", "dispute"]},
    detail=STR, paths=arr(STR), item=NSTR, finding=NSTR, capability=NSTR, depends_on=NINT, depends_quote=NSTR,
    command=NSTR, cwd=NSTR, timeout_s=NINT,
)
BUILD = obj(
    status={"type": "string", "enum": ["done", "blocked"]}, note=STR, tests=arr(STR), commands=arr(COMMAND),
    dispositions=arr(obj(test=STR, disposition=STR)), decisions=arr(DECISION), requests=arr(REQUEST),
)
RESOLVED = obj(files=arr(STR), note=STR)
FINDING = obj(title=STR, item=NSTR, quote=NSTR, invariant=NSTR, observed=STR, expected=STR, reproduction=NSTR,
              cwd=STR, probe=NSTR, file=NSTR, line=NINT, severity=INT)
EXAMINE = obj(
    verdicts=arr(obj(item=STR, verdict={"type": "string", "enum": ["met", "unmet"]}, quote=STR, note=STR)),
    findings=arr(FINDING),
    probes=arr(obj(file=STR, criterion=STR, command=STR, cwd=STR, content=STR)),
    certify=BOOL,
    summary=STR,
)
DECIDE = obj(decisions=arr(obj(request=STR, approve=BOOL, reason=STR,
                               dispositions=arr(obj(test=STR, disposition=STR)))))
ARBITRATE = obj(upheld=BOOL, reason=STR)

BY_ROLE = {
    "explore": EXPLORE,
    "smoke": SMOKE,
    "plan": PLAN,
    "triage": TRIAGE,
    "build": BUILD,
    "resolve_locked": RESOLVED,
    "examine": EXAMINE,
    "decide": DECIDE,
    "arbitrate": ARBITRATE,
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
