"""Act III demos: the agent loop on P00, plan first vs straight to code, and the context bomb.

    uv run agent_demo.py reset  <loop|plan|bomb>                    # clean state, nothing else
    uv run agent_demo.py run    <loop|plan|bomb> --via claude|codex  # reset, then the live demo
    uv run agent_demo.py run    <demo> --via <cli> --record --run 1  # also write recorded/
    uv run agent_demo.py replay <demo> --via <cli> [--run 2]         # the fallback, no CLI, no network

Instructor-only and Linux-only (ADR 0010). Standard library only. It drives Claude Code
(`claude -p`) or Codex (`codex exec`) through the CLI's own login and never reads an API key.
Every demo works in <tempdir>/cursus-s1-agent/<demo>/, outside the course checkout:
loop and plan get a fresh flipped-sense P00 export (exercises/p00-lab/export.py) synced
offline from the warmed uv cache, bomb gets a folder holding only mcp.json. `run` always
starts with the same reset as the `reset` command.
"""

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = Path(__file__).resolve().parent
SESSION = HERE.parents[2]
PACK = SESSION / "exercises" / "p00-lab"
RECORDED = HERE / "recorded"
SERVER = HERE / "context_bomb.py"
DEFAULT_WORK_ROOT = Path(tempfile.gettempdir()) / "cursus-s1-agent"

DEMOS = ("loop", "plan", "bomb")
CLIS = ("claude", "codex")
NAMES = {"claude": "Claude Code", "codex": "Codex"}
LOGIN = {"claude": "run `claude` and type /login", "codex": "run `codex login`"}
BUG = "flipped-sense"
SUITE = "test_p00_contract.py"
MODEL_FILE = "p00_model.py"

# The loop and plan demos use the models the lab-ladder rehearsal proved on P00; the context
# bomb only needs a one-word reply, so it uses the small models of the Act I demos.
MODELS = {
    "loop": {"claude": "claude-opus-5-5", "codex": "gpt-6-astra"},
    "plan": {"claude": "claude-opus-5-5", "codex": "gpt-6-astra"},
    "bomb": {"claude": "claude-haiku-5-5", "codex": "gpt-6-luna"},
}
EFFORT = {
    "loop": {"claude": "medium", "codex": "medium"},
    "plan": {"claude": "medium", "codex": "medium"},
    "bomb": {"claude": "low", "codex": "low"},
}

# One task for every loop and plan rehearsal, with either CLI (its sha256 is in each meta).
LOOP_PROMPT = (
    "The tests in this folder fail. First read README.md and p00_model.py. Then run "
    "`uv run pytest` and read the failure. Make every test pass by editing only p00_model.py: "
    "do not change the tests, p00_checker.py or anything in data/, and do not hard-code an "
    "expected answer. Then run `uv run pytest` again and check that every test passes. Finish "
    "with one sentence naming the contract that was broken and the line you changed."
)
PLAN_PREFIX = (
    "Plan only. Do not edit, create or delete any file, and do not run anything that changes "
    "the folder. Read what you need, then reply with a short numbered plan that another agent "
    "will carry out. The task:\n\n"
)
BUILD_TEMPLATE = "Implement this plan:\n\n{plan}\n\nThe task the plan was written for:\n\n{task}"
OK_PROMPT = "Reply with exactly: OK"

# Agents run `uv run pytest` offline, without syncing (reset already did) and without uv's
# persistent cache, which Codex's workspace-write sandbox cannot write.
AGENT_ENV = {"UV_OFFLINE": "1", "UV_NO_SYNC": "1", "UV_NO_CACHE": "1"}
TOOL_SEARCH_OFF = {"ENABLE_TOOL_SEARCH": "false"}
AGENT_TIMEOUT_S = 900
GIT_REDIRECTS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
                 "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES")
PRIVATE_KEYS = {"session_id", "thread_id", "uuid", "message_id", "request_id"}
CODEX_TOOL_ITEMS = {"command_execution", "file_change", "mcp_tool_call", "web_search", "tool_call"}
PYTEST_LINE = re.compile(r"^(?:FAILED \S+.*|.*\b\d+ (?:passed|failed)\b.*)$", re.M)


class Failure(Exception):
    """A user-facing error: printed as is, without a traceback."""


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def seconds_between(start, end):
    parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (parse(end) - parse(start)).total_seconds()


def sha256(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def stem(demo, cli, run):
    return f"{demo}-{cli}-run{run}"


def replay_command(demo, cli, run=1):
    return f"uv run agent_demo.py replay {demo} --via {cli}" + (f" --run {run}" if run != 1 else "")


# ── Environment and subprocesses ─────────────────────────────────────

def base_env():
    """os.environ without the session venv that `uv run agent_demo.py` put in front."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_REDIRECTS}
    venv = env.pop("VIRTUAL_ENV", None)
    if venv:
        bin_dir = str(Path(venv) / "bin")
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if p != bin_dir)
    return env


def agent_env(extra=None):
    env = base_env()
    env.pop("ENABLE_TOOL_SEARCH", None)
    env.update(AGENT_ENV)
    env.update(extra or {})
    return env


def quiet(argv, cwd, env=None, timeout=120):
    try:
        return subprocess.run([str(a) for a in argv], cwd=cwd, env=env or base_env(),
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Failure(f"could not run {argv[0]} ({type(error).__name__}: {error})") from None


def git(folder, *args):
    done = quiet(["git", "-C", folder, *args], folder)
    if done.returncode != 0:
        raise Failure(f"git {' '.join(args)} failed in {folder}: {done.stderr.strip()}")
    return done.stdout


# ── Workspaces and reset ─────────────────────────────────────────────

def workspace(demo, work_root):
    return Path(work_root).expanduser().absolute() / demo


def mcp_config():
    return {"mcpServers": {"context_bomb": {"command": sys.executable, "args": [str(SERVER)]}}}


def contract(folder):
    """The export's own pytest on the unchanged contract suite: (exit code, failing ids, summary)."""
    python = folder / ".venv" / "bin" / "python"
    env = dict(base_env(), PYTHONDONTWRITEBYTECODE="1")
    done = quiet([python if python.exists() else sys.executable, "-B", "-m", "pytest", "-q", "-rf",
                  "-p", "no:cacheprovider", SUITE], folder, env, timeout=300)
    failing = re.findall(r"^FAILED (\S+)", done.stdout, re.M)
    lines = [line for line in done.stdout.splitlines() if re.search(r"\b\d+ (?:passed|failed)\b", line)]
    return done.returncode, failing, (lines[-1].strip("= ") if lines else done.stdout.strip()[-200:])


def reset(demo, work_root, announce=True):
    folder = workspace(demo, work_root)
    checkout = next((p for p in HERE.parents if (p / ".git").exists()), None)
    if checkout is not None and folder.resolve().is_relative_to(checkout.resolve()):
        raise Failure(f"--work-root must be outside the course checkout ({checkout})")
    if folder.is_symlink() or folder.is_file():
        folder.unlink()
    elif folder.exists():
        shutil.rmtree(folder)
    folder.parent.mkdir(parents=True, exist_ok=True)
    if demo == "bomb":
        folder.mkdir()
        (folder / "mcp.json").write_text(json.dumps(mcp_config(), indent=2) + "\n", encoding="utf-8")
        if announce:
            print(f"reset bomb: {folder} holds only mcp.json (server: {SERVER.name}, not registered anywhere)")
        return folder
    exported = quiet([sys.executable, PACK / "export.py", "--bug", BUG, "--out", folder], PACK)
    if exported.returncode != 0:
        raise Failure(f"export.py failed: {exported.stderr.strip()}")
    uv = shutil.which("uv")
    env = base_env()
    env.pop("UV_NO_SYNC", None)
    synced = quiet([uv or "uv", "sync", "--locked", "--offline", "--quiet"], folder, env, timeout=600)
    if synced.returncode != 0:
        raise Failure("uv sync --locked --offline failed in the export (warm the cache with "
                      f"`uv sync` in sessions/01-fundamentals first): {synced.stderr.strip()[-300:]}\n"
                      f"Or replay the recording: {replay_command(demo, 'claude')}")
    if announce:
        code, failing, summary = contract(folder)
        print(f"reset {demo}: fresh {BUG} export at {folder}, synced offline")
        print(f"  pytest: {summary}" + (f" ({', '.join(failing)})" if failing else ""))
    return folder


def snapshot(folder, pytest=True):
    """Content state: sha256 of every tracked or untracked-not-ignored file, the diff, the model."""
    tracked = [n for n in git(folder, "ls-files", "-z").split("\0") if n]
    untracked = [n for n in git(folder, "ls-files", "--others", "--exclude-standard", "-z").split("\0") if n]
    names = sorted({n for n in tracked + untracked if (folder / n).is_file()})
    diffed = [n for n in git(folder, "diff", "--name-only", "-z", "HEAD").split("\0") if n]
    state = {
        "export_tree": git(folder, "rev-parse", "HEAD^{tree}").strip(),
        "file_hashes": {n: sha256((folder / n).read_bytes()) for n in names},
        "changed_files": sorted(set(diffed) | set(untracked)),
        "p00_model_py": (folder / MODEL_FILE).read_bytes().decode("utf-8"),
    }
    if pytest:
        code, failing, summary = contract(folder)
        state.update(pytest_exit_code=code, failing_test_ids=failing, pytest_summary=summary)
    return state


# ── Scrubbing ────────────────────────────────────────────────────────

class Scrubber:
    """Home to ~, user to <user>, work root to <work>, IDs to placeholders.

    In raw streams the agent's own folder becomes relative ('.'), so a scrubbed plan still
    makes sense to the agent that builds it; in metadata it stays <work>/<demo>.
    """

    def __init__(self, folder, work_root, relative):
        pairs = []
        for base in dict.fromkeys([folder, folder.resolve()]):
            pairs += [(str(base) + "/", ""), (str(base), ".")] if relative else []
        for base in dict.fromkeys([Path(work_root).absolute(), Path(work_root).resolve()]):
            pairs.append((str(base), "<work>"))
        pairs.append((str(SESSION), "<session>"))
        pairs.append((str(SESSION.parents[1]), "<repo>"))
        pairs.append((str(Path.home()), "~"))
        self.pairs = pairs
        user = getpass.getuser()
        self.user = re.compile(rf"\b{re.escape(user)}\b") if len(user) > 2 else None

    def text(self, value):
        for old, new in self.pairs:
            value = value.replace(old, new)
        value = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "<account>", value)
        return self.user.sub("<user>", value) if self.user else value

    def value(self, value, parent=None):
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                if item is not None and (key in PRIVATE_KEYS or (key == "id" and parent == "message")):
                    out[key] = f"<{'message_id' if key == 'id' else key}>"
                else:
                    out[key] = self.value(item, key)
            return out
        if isinstance(value, list):
            return [self.value(item, parent) for item in value]
        if isinstance(value, str):
            return self.text(value)
        return value


# ── Native event decoding (shared by live output, recording and replay) ──

def parse_lines(text):
    events, dropped = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            dropped += 1
            continue
        if isinstance(event, dict) and isinstance(event.get("type"), str):
            events.append(event)
        else:
            dropped += 1
    return events, dropped


def block_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(block_text(v) for v in value)
    if isinstance(value, dict):
        return str(value.get("text", value.get("content", "")))
    return ""


def tool_calls(events, cli):
    """Every native tool call with its result, in stream order."""
    calls = []
    if cli == "claude":
        pending = []
        for event in events:
            for block in (event.get("message") or {}).get("content", []) if event.get("type") in {"assistant", "user"} else []:
                if not isinstance(block, dict):
                    continue
                if event["type"] == "assistant" and block.get("type") == "tool_use":
                    call = {"name": block.get("name", "?"), "input": block.get("input", {}),
                            "id": block.get("id"), "output": "", "error": False}
                    pending.append(call)
                    calls.append(call)
                elif event["type"] == "user" and block.get("type") == "tool_result":
                    match = next((c for c in pending if c["id"] == block.get("tool_use_id")), None)
                    if match:
                        pending.remove(match)
                        match.update(output=block_text(block.get("content", "")), error=bool(block.get("is_error")))
    else:
        for event in events:
            item = event.get("item") or {}
            if event.get("type") == "item.completed" and item.get("type") in CODEX_TOOL_ITEMS:
                calls.append({"name": item["type"], "input": item,
                              "output": item.get("aggregated_output", block_text(item.get("result", ""))),
                              "error": item.get("exit_code", 0) != 0 or item.get("status") == "failed"})
    return calls


def usage_counts(events, cli):
    """Token counters exactly as the CLI reported them; total = input + output (+ Claude's cache)."""
    names = {"input": ("input_tokens",), "output": ("output_tokens",),
             "cache_read": ("cache_read_input_tokens",), "cache_write": ("cache_creation_input_tokens",),
             "cached_input": ("cached_input_tokens",), "reasoning_output": ("reasoning_output_tokens",)}
    if cli == "claude":
        results = [e for e in events if e.get("type") == "result"]
        rows = [results[-1]["usage"]] if results and isinstance(results[-1].get("usage"), dict) else []
    else:
        rows = [e["usage"] for e in events if e.get("type") == "turn.completed" and isinstance(e.get("usage"), dict)]
    counts = dict.fromkeys(names, 0)
    for row in rows:
        for name, keys in names.items():
            counts[name] += sum(row.get(k, 0) for k in keys if isinstance(row.get(k), int))
    counts["total"] = counts["input"] + counts["output"]
    if cli == "claude":
        counts["total"] += counts["cache_read"] + counts["cache_write"]
    return counts


def final_text(events, cli):
    if cli == "claude":
        return "\n".join(e.get("result", "") for e in events if e.get("type") == "result")
    return "\n".join(e.get("item", {}).get("text", "") for e in events
                     if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "agent_message")


def reported_models(events):
    found = []
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "model" and isinstance(child, str) and child not in found:
                    found.append(child)
                elif key == "modelUsage" and isinstance(child, dict):
                    found.extend(m for m in child if m not in found)
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(events)
    return found


def pytest_verdict(call):
    if not re.search(r"\bpytest\b", json.dumps(call["input"])):
        return None
    output = call["output"]
    if re.search(r"\b(?:[1-9]\d* failed|FAILED\s+\S*test_|FAILURES)\b", output):
        return "red"
    if not call["error"] and re.search(r"\b[1-9]\d* passed\b", output):
        return "green"
    return None


def describe_call(call, cli):
    data = call["input"]
    if cli == "claude":
        detail = data.get("file_path") or data.get("command") or data.get("pattern") or data.get("description") or ""
        if call["name"] == "ExitPlanMode":
            detail = f"plan of {len(str(data.get('plan', '')))} characters"
        label = call["name"]
    elif call["name"] == "command_execution":
        label, detail = "exec", data.get("command", "")
    elif call["name"] == "file_change":
        label = "edit"
        detail = ", ".join(f"{Path(c.get('path', '?')).name} ({c.get('kind', '?')})" for c in data.get("changes", []))
    elif call["name"] == "mcp_tool_call":
        label, detail = "mcp", f"{data.get('server')}.{data.get('tool')} ({data.get('status')})"
    else:
        label, detail = call["name"], ""
    detail = str(detail).replace("\n", " ")
    lines = [f"  tool  {label:<5} {detail[:110]}"]
    verdict = pytest_verdict(call)
    if verdict:
        for line in PYTEST_LINE.findall(call["output"])[-3:]:
            lines.append(f"        {'RED  ' if verdict == 'red' else 'GREEN'} {line.strip()[:110]}")
    elif call["error"]:
        lines.append(f"        error {call['output'].strip().splitlines()[0][:110] if call['output'].strip() else ''}")
    return lines


def token_header(cli):
    if cli == "claude":
        return f"  {'arm':<22}{'input':>9}{'output':>9}{'cache read':>12}{'cache write':>13}{'total':>10}"
    return f"  {'arm':<22}{'input':>9}{'cached in':>11}{'output':>9}{'reasoning':>11}{'total':>10}"


def token_row(cli, name, c, delta=None):
    tail = "" if delta is None else f"   Δ total {delta:+,}"
    if cli == "claude":
        return (f"  {name:<22}{c['input']:>9,}{c['output']:>9,}{c['cache_read']:>12,}"
                f"{c['cache_write']:>13,}{c['total']:>10,}{tail}")
    return (f"  {name:<22}{c['input']:>9,}{c['cached_input']:>11,}{c['output']:>9,}"
            f"{c['reasoning_output']:>11,}{c['total']:>10,}{tail}")


# ── Running a CLI ────────────────────────────────────────────────────

def claude_argv(prompt, model, effort, mode, mcp=None):
    argv = ["claude", "-p", prompt, "--model", model, "--effort", effort]
    if mode in {"build", "plan"}:
        argv += ["--permission-mode", "plan" if mode == "plan" else "acceptEdits"]
    if mode == "build":
        argv += ["--allowedTools", "Bash(uv run pytest:*)"]
    argv += ["--strict-mcp-config"] + (["--mcp-config", str(mcp)] if mcp else [])
    return argv + ["--no-session-persistence", "--output-format", "stream-json", "--verbose"]


def codex_server_overrides():
    server = mcp_config()["mcpServers"]["context_bomb"]
    return ["-c", f"mcp_servers.context_bomb.command={json.dumps(server['command'])}",
            "-c", f"mcp_servers.context_bomb.args={json.dumps(server['args'])}",
            "-c", "mcp_servers.context_bomb.required=true"]


def codex_argv(prompt, model, effort, mode, folder, extra=()):
    sandbox = {"build": "workspace-write", "plan": "read-only", "bomb": "read-only"}[mode]
    argv = ["codex", "exec", "--json", "--ephemeral", "-C", str(folder), "--sandbox", sandbox,
            "-c", 'approval_policy="never"', "-m", model, "-c", f'model_reasoning_effort="{effort}"']
    if mode == "bomb":
        argv.append("--skip-git-repo-check")
    return argv + list(extra) + [prompt]


def shown(argv, prompt, scrub):
    return [("<prompt>" if a == prompt else scrub.text(a)) for a in argv]


def check_login(cli, demo):
    if shutil.which(cli) is None:
        raise Failure(f"{cli}: not installed (not found on PATH); install {NAMES[cli]}, then {LOGIN[cli]}\n"
                      f"Or replay the recording: {replay_command(demo, cli)}")
    done = quiet(["claude", "auth", "status"] if cli == "claude" else ["codex", "login", "status"], HERE, timeout=60)
    text = done.stdout + done.stderr
    try:
        logged = json.loads(done.stdout).get("loggedIn")
    except (ValueError, AttributeError):
        logged = None
    if logged is False or re.search(r"not logged in|logged out", text, re.I) or (logged is None and done.returncode != 0):
        raise Failure(f"{cli}: installed but not logged in; {LOGIN[cli]}\n"
                      f"Or replay the recording: {replay_command(demo, cli)}")


def cli_version(cli):
    done = quiet([cli, "--version"], HERE, timeout=60)
    return done.stdout.strip() or "unknown"


def call_agent(cli, argv, cwd, env, label):
    """Run one headless call, printing each native event as it arrives. Returns the raw result."""
    print(f"\n── {label}: {NAMES[cli]} ──", flush=True)
    started = utc_now()
    try:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    except OSError as error:
        raise Failure(f"{cli} could not start ({error})") from None
    errors = []
    reader = threading.Thread(target=lambda: errors.append(child.stderr.read()), daemon=True)
    reader.start()
    timer = threading.Timer(AGENT_TIMEOUT_S, child.kill)
    timer.start()
    lines, pending = [], []
    try:
        for line in child.stdout:
            lines.append(line)
            events, _ = parse_lines(line)
            for event in events:
                for text in live_lines(event, cli, pending):
                    print(text, flush=True)
        code = child.wait()
    finally:
        timer.cancel()
    reader.join(timeout=10)
    return {"stdout": "".join(lines), "stderr": "".join(errors), "exit_code": code,
            "started_at": started, "ended_at": utc_now()}


def live_lines(event, cli, pending):
    if cli == "claude":
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            servers = ", ".join(f"{s.get('name')} {s.get('status')}" for s in event.get("mcp_servers", []))
            return [f"  init  model {event.get('model')}, {len(event.get('tools', []))} tools"
                    + (f", MCP: {servers}" if servers else "")]
        if kind == "assistant":
            out = []
            for block in (event.get("message") or {}).get("content", []):
                if block.get("type") == "tool_use":
                    pending.append({"name": block.get("name"), "input": block.get("input", {}),
                                    "id": block.get("id"), "output": "", "error": False})
                    out.append(describe_call(pending[-1], cli)[0])
            return out
        if kind == "user":
            out = []
            for block in (event.get("message") or {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    match = next((c for c in pending if c["id"] == block.get("tool_use_id")), None)
                    if match:
                        pending.remove(match)
                        match.update(output=block_text(block.get("content", "")), error=bool(block.get("is_error")))
                        out += describe_call(match, cli)[1:]
            return out
        if kind == "result":
            return [f"  done  {str(event.get('result', '')).strip()[:300]}"]
        return []
    item = event.get("item") or {}
    if event.get("type") == "item.completed" and item.get("type") in CODEX_TOOL_ITEMS:
        return describe_call(tool_calls([event], cli)[0], cli)
    if event.get("type") == "item.completed" and item.get("type") == "agent_message":
        return [f"  says  {item.get('text', '').strip()[:300]}"]
    return []


def agent_row(cli, result, argv, prompt, scrub_stream, scrub_meta, env_extra=None):
    """One call's metadata, and its scrubbed raw events."""
    events, dropped = parse_lines(result["stdout"])
    events = scrub_stream.value(events)
    row = {
        "command": shown(argv, prompt, scrub_meta),
        "prompt_sha256": sha256(prompt),
        "started_at": result["started_at"],
        "ended_at": result["ended_at"],
        "exit_code": result["exit_code"],
        "usage": usage_counts(events, cli),
        "tool_calls": len(tool_calls(events, cli)),
        "dropped_stdout_lines": dropped,
    }
    if env_extra:
        row["env"] = dict(env_extra)
    if result["exit_code"] != 0:
        row["stderr_tail"] = scrub_meta.text(result["stderr"].strip()[-600:])
    return row, events


def write_raw(name, events):
    RECORDED.mkdir(exist_ok=True)
    text = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)
    (RECORDED / name).write_text(text, encoding="utf-8")


def write_meta(name, meta):
    RECORDED.mkdir(exist_ok=True)
    (RECORDED / name).write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def common_meta(demo, cli, run, version, started):
    return {"demo": demo, "cli": cli, "run": run, "cli_version": version,
            "model": MODELS[demo][cli], "model_source": "requested", "reported_models": [],
            "effort": EFFORT[demo][cli], "started_at": started, "ended_at": None,
            "host": "Linux (instructor machine), CLI logged in with its own account"}


def settle_model(meta, all_events):
    models = []
    for events in all_events:
        models += [m for m in reported_models(events) if m not in models]
    meta["reported_models"] = models
    meta["model_source"] = "reported" if all(meta["model"] in reported_models(e) for e in all_events) else "requested"


# ── The loop and plan demos ──────────────────────────────────────────

def build_call(cli, prompt, folder, mode, demo):
    model, effort = MODELS[demo][cli], EFFORT[demo][cli]
    if cli == "claude":
        return claude_argv(prompt, model, effort, mode)
    return codex_argv(prompt, model, effort, mode, folder)


def fresh(demo, work_root):
    folder = reset(demo, work_root, announce=False)
    state = snapshot(folder)
    if state["pytest_exit_code"] != 1 or not any("test_objective_contract" in t for t in state["failing_test_ids"]):
        raise Failure(f"the fresh export does not fail the objective contract: {state['pytest_summary']}")
    return folder, state


def run_loop(cli, args, version):
    work_root = Path(args.work_root)
    folder, pre = fresh("loop", work_root)
    print(f"export: {folder}\n  pytest before the agent: {pre['pytest_summary']}")
    stream, meta_scrub = Scrubber(folder, work_root, True), Scrubber(folder, work_root, False)
    argv = build_call(cli, LOOP_PROMPT, folder, "build", "loop")
    result = call_agent(cli, argv, folder, agent_env(), "the loop")
    row, events = agent_row(cli, result, argv, LOOP_PROMPT, stream, meta_scrub, AGENT_ENV)
    post = snapshot(folder)
    meta = common_meta("loop", cli, args.run, version, result["started_at"])
    meta.update(row)
    meta.update(ended_at=utc_now(), cwd="<work>/loop", prompt=LOOP_PROMPT,
                raw=f"{stem('loop', cli, args.run)}.jsonl", pre_state=pre, post_state=post)
    settle_model(meta, [events])
    print(f"\n  pytest after the agent (run by this script): {post['pytest_summary']}")
    print(f"  files changed: {', '.join(post['changed_files']) or 'none'}")
    print(token_header(cli))
    print(token_row(cli, "loop", meta["usage"]))
    if args.record:
        write_raw(meta["raw"], events)
        write_meta(f"{stem('loop', cli, args.run)}.meta.json", meta)
        print(f"recorded recorded/{stem('loop', cli, args.run)}.*")
    return result["exit_code"]


def plan_text_of(events, cli):
    """The plan as the recorded CLI version delivers it, and where it came from."""
    if cli == "claude":
        for call in tool_calls(events, cli):
            plan = call["input"].get("plan") if call["name"] == "ExitPlanMode" else None
            if isinstance(plan, str) and plan.strip():
                return plan, "ExitPlanMode tool input"
        return final_text(events, cli), "result message"
    return final_text(events, cli), "agent_message items (joined)"


def run_plan(cli, args, version):
    work_root = Path(args.work_root)
    meta = None
    arms, all_events = {}, []
    run = args.run

    folder, pre = fresh("plan", work_root)
    stream, meta_scrub = Scrubber(folder, work_root, True), Scrubber(folder, work_root, False)
    argv = build_call(cli, LOOP_PROMPT, folder, "build", "plan")
    result = call_agent(cli, argv, folder, agent_env(), "arm 1, straight to code")
    meta = common_meta("plan", cli, run, version, result["started_at"])
    row, events = agent_row(cli, result, argv, LOOP_PROMPT, stream, meta_scrub, AGENT_ENV)
    row.update(prompt=LOOP_PROMPT, pre_state=pre, post_state=snapshot(folder))
    arms["direct"], all_events = row, [events]
    raws = {"direct": events}

    folder, pre = fresh("plan", work_root)
    prompt = PLAN_PREFIX + LOOP_PROMPT
    argv = build_call(cli, prompt, folder, "plan", "plan")
    result = call_agent(cli, argv, folder, agent_env(), "arm 2a, plan only")
    row, events = agent_row(cli, result, argv, prompt, stream, meta_scrub, AGENT_ENV)
    plan, source = plan_text_of(events, cli)
    after_plan = snapshot(folder)
    row.update(prompt=prompt, plan_source=source, plan_text=plan, pre_state=pre, post_state=after_plan)
    arms["plan"], raws["plan"] = row, events
    all_events.append(events)
    if not plan.strip():
        raise Failure(f"the plan call returned no plan text (source tried: {source}); not building")
    if after_plan["file_hashes"] != pre["file_hashes"] or after_plan["changed_files"]:
        raise Failure("the plan call changed the export; not building")

    prompt = BUILD_TEMPLATE.format(plan=plan, task=LOOP_PROMPT)
    argv = build_call(cli, prompt, folder, "build", "plan")
    result = call_agent(cli, argv, folder, agent_env(), "arm 2b, build the plan")
    row, events = agent_row(cli, result, argv, prompt, stream, meta_scrub, AGENT_ENV)
    row.update(prompt=prompt, pre_state=after_plan, post_state=snapshot(folder))
    arms["build"], raws["build"] = row, events
    all_events.append(events)

    meta.update(ended_at=utc_now(), cwd="<work>/plan", task_prompt_sha256=sha256(LOOP_PROMPT),
                exit_codes={name: arm["exit_code"] for name, arm in arms.items()}, arms=arms)
    meta["comparison"] = comparison(arms)
    settle_model(meta, all_events)
    print_comparison(cli, meta)
    if args.record:
        for name, events in raws.items():
            write_raw(f"{stem('plan', cli, run)}-{name}.jsonl", events)
        write_meta(f"{stem('plan', cli, run)}.meta.json", meta)
        print(f"recorded recorded/{stem('plan', cli, run)}*")
    return max(abs(arm["exit_code"]) for arm in arms.values())


def comparison(arms):
    def measure(names, last):
        return {"tokens": sum(arms[n]["usage"]["total"] for n in names),
                "tool_calls": sum(arms[n]["tool_calls"] for n in names),
                "seconds": sum(seconds_between(arms[n]["started_at"], arms[n]["ended_at"]) for n in names),
                "files_changed": len(arms[last]["post_state"]["changed_files"]),
                "pytest_exit_code": arms[last]["post_state"]["pytest_exit_code"]}
    return {"direct": measure(["direct"], "direct"), "planned": measure(["plan", "build"], "build")}


def print_comparison(cli, meta):
    print(f"\n  comparison ({NAMES[cli]}, {meta['model']}, effort {meta['effort']}; token usage as reported)")
    print(f"  {'arm':<10}{'tokens':>10}{'tool calls':>12}{'seconds':>9}{'files changed':>15}{'final pytest':>14}")
    for name, row in meta["comparison"].items():
        verdict = "passed" if row["pytest_exit_code"] == 0 else f"failed ({row['pytest_exit_code']})"
        print(f"  {name:<10}{row['tokens']:>10,}{row['tool_calls']:>12}{row['seconds']:>9.0f}"
              f"{row['files_changed']:>15}{verdict:>14}")


# ── The context bomb ─────────────────────────────────────────────────

def codex_mcp_list(extra, scrub):
    done = quiet(["codex", "mcp", "list", "--json", *extra], HERE, agent_env(), timeout=60)
    try:
        return scrub.value(json.loads(done.stdout))
    except ValueError:
        return scrub.text((done.stdout + done.stderr).strip()) or f"(codex mcp list exited {done.returncode})"


def claude_context(model, effort, folder, mcp, scrub, label, env_extra=None):
    argv = ["claude", "-p", "/context", "--model", model, "--effort", effort, "--strict-mcp-config"]
    argv += (["--mcp-config", str(mcp)] if mcp else []) + ["--no-session-persistence",
                                                            "--output-format", "stream-json", "--verbose"]
    print(f"\n── /context {label} ──", flush=True)
    done = quiet(argv, folder, agent_env(env_extra), timeout=300)
    events, _ = parse_lines(done.stdout)
    text = final_text(events, "claude").strip()
    print("\n".join("  " + line for line in text.splitlines()[:22]))
    prefix = "".join(f"{k}={v} " for k, v in (env_extra or {}).items())
    header = f"$ {prefix}{' '.join(scrub.text(a) for a in argv)}\n# captured {utc_now()} with {cli_version('claude')}\n\n"
    info = {"command": [scrub.text(a) for a in argv], "exit_code": done.returncode}
    if env_extra:
        info["env"] = dict(env_extra)
    return header + scrub.text(text) + "\n", info


def tmux(*args, check=True):
    done = quiet(["tmux", *args], HERE, timeout=30)
    if check and done.returncode != 0:
        raise Failure(f"tmux {args[0]} failed: {done.stderr.strip()}")
    return done.stdout


def wait_for(session, pattern, seconds):
    deadline = time.monotonic() + seconds
    pane = ""
    while time.monotonic() < deadline:
        pane = tmux("capture-pane", "-p", "-J", "-t", session, "-S", "-400")
        if re.search(r"Update available.*\n(?:.*\n)*.*esc skip", pane):
            tmux("send-keys", "-t", session, "Escape")  # skip the update offer: keep the pinned CLI
            time.sleep(2)
            continue
        if re.search(pattern, pane, re.M):
            return pane
        time.sleep(1)
    raise Failure(f"the Codex TUI never showed {pattern!r}; last screen:\n{pane[-1500:]}")


def codex_status(model, effort, folder, extra, scrub, label):
    """Codex's /context equivalent: /status (and /mcp) in the TUI, captured through tmux."""
    if shutil.which("tmux") is None:
        raise Failure("tmux is needed to capture the Codex TUI's /status")
    session = f"cursus-s1-bomb-{os.getpid()}"
    argv = ["codex", "-m", model, "-c", f'model_reasoning_effort="{effort}"', "--sandbox", "read-only",
            "-c", 'approval_policy="never"', *extra]
    print(f"\n── /status {label} (Codex TUI in tmux) ──", flush=True)
    env = " ".join(f"{k}={v}" for k, v in AGENT_ENV.items())
    tmux("new-session", "-d", "-s", session, "-x", "200", "-y", "60", "-c", str(folder),
         "env " + env + " " + " ".join(shell_quote(a) for a in argv))
    try:
        wait_for(session, r"Context \d+% left", 90)
        for keys, pattern, seconds in ((OK_PROMPT, r"^\s*• OK\s*$", 180),
                                       ("/status", r"Context window:", 60),
                                       ("/mcp", r"MCP Tools|No MCP", 60)):
            tmux("send-keys", "-t", session, "-l", keys)
            time.sleep(0.7)
            tmux("send-keys", "-t", session, "Enter")
            pane = wait_for(session, pattern, seconds)
            time.sleep(2)
        pane = tmux("capture-pane", "-p", "-J", "-t", session, "-S", "-400")
    finally:
        tmux("kill-session", "-t", session, check=False)
    lines = [line.rstrip() for line in pane.splitlines()]
    start = next((i for i, line in enumerate(lines) if "OpenAI Codex (v" in line), 0)
    body = "\n".join(line for line in lines[start:] if line.strip())
    body = re.sub(r"(Session:\s+)\S+", r"\1<session_id>", body)
    text = scrub.text(body)
    print("\n".join("  " + line for line in text.splitlines() if re.search(r"Model:|Context window|context_bomb|MCP", line)))
    header = (f"$ {' '.join(scrub.text(a) for a in argv)}   # in tmux, then: {OK_PROMPT} · /status · /mcp\n"
              f"# captured {utc_now()} with {cli_version('codex')}\n\n")
    return header + text + "\n", {"command": [scrub.text(a) for a in argv], "keys": [OK_PROMPT, "/status", "/mcp"],
                                  "exit_code": 0}


def shell_quote(value):
    return "'" + value.replace("'", "'\\''") + "'"


def run_bomb(cli, args, version):
    work_root = Path(args.work_root)
    folder = reset("bomb", work_root, announce=False)
    pre = {"file_hashes": {"mcp.json": sha256((folder / "mcp.json").read_bytes())}}
    stream, meta_scrub = Scrubber(folder, work_root, False), Scrubber(folder, work_root, False)
    model, effort, run = MODELS["bomb"][cli], EFFORT["bomb"][cli], args.run
    meta = common_meta("bomb", cli, run, version, utc_now())
    arms, raws, captures, codes = {}, {}, {}, {}
    if cli == "claude":
        meta["context_method"] = ("claude -p /context (print mode; the slash command's result text). The after "
                                  "capture holds two: CLI defaults, then ENABLE_TOOL_SEARCH=false")
        captures["context-before"], info = claude_context(model, effort, folder, None, meta_scrub, "before: no MCP server")
        codes["context-before"] = info["exit_code"]
        meta["captures"] = {"context-before": info}
        plan = (("without", None, None), ("with", folder / "mcp.json", None),
                ("with-tool-search-off", folder / "mcp.json", TOOL_SEARCH_OFF))
    else:
        meta["context_method"] = ("Codex TUI /status (and /mcp) after one 'Reply with exactly: OK' turn, "
                                  "captured with tmux capture-pane")
        captures["status-before"], info = codex_status(model, effort, folder, [], meta_scrub, "before: no MCP server")
        codes["status-before"] = info["exit_code"]
        meta["captures"] = {"status-before": info}
        plan = (("without", None, None), ("with", "override", None))
    for name, mcp, extra_env in plan:
        if cli == "claude":
            argv = claude_argv(OK_PROMPT, model, effort, "bomb", mcp)
        else:
            overrides = codex_server_overrides() if mcp else []
            argv = codex_argv(OK_PROMPT, model, effort, "bomb", folder, overrides)
        result = call_agent(cli, argv, folder, agent_env(extra_env), f"arm {name}: {OK_PROMPT!r}")
        row, events = agent_row(cli, result, argv, OK_PROMPT, stream, meta_scrub, extra_env)
        if cli == "claude":
            init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), {})
            tools = init.get("tools", [])
            row["init"] = {"tools": len(tools), "tool_search_tool": "ToolSearch" in tools,
                           "bomb_tools": sorted(t for t in tools if "bomb" in t),
                           "mcp_servers": init.get("mcp_servers", [])}
        else:
            row["effective_mcp_servers"] = codex_mcp_list(codex_server_overrides() if mcp else [], meta_scrub)
            row["server_required"] = bool(mcp)
        row["answer"] = final_text(events, cli).strip()
        arms[name], raws[name] = row, events
        codes[name] = row["exit_code"]
    if cli == "claude":
        defaults, info = claude_context(model, effort, folder, folder / "mcp.json", meta_scrub,
                                        "after: context bomb, CLI defaults")
        off, off_info = claude_context(model, effort, folder, folder / "mcp.json", meta_scrub,
                                       "after: context bomb, tool search off", TOOL_SEARCH_OFF)
        captures["context-after"] = defaults + "\n" + off
        codes["context-after"] = info["exit_code"]
        codes["context-after-tool-search-off"] = off_info["exit_code"]
        meta["captures"]["context-after"] = info
        meta["captures"]["context-after-tool-search-off"] = off_info
    else:
        captures["status-after"], info = codex_status(model, effort, folder, codex_server_overrides(), meta_scrub,
                                                      "after: context bomb")
        codes["status-after"] = info["exit_code"]
        meta["captures"]["status-after"] = info
    meta.update(ended_at=utc_now(), cwd="<work>/bomb", prompt=OK_PROMPT, prompt_sha256=sha256(OK_PROMPT),
                pre_state=pre, exit_codes=codes, arms=arms)
    settle_model(meta, list(raws.values()))
    print_bomb(cli, meta)
    if args.record:
        for name, events in raws.items():
            write_raw(f"{stem('bomb', cli, run)}-{name}.jsonl", events)
        for name, text in captures.items():
            (RECORDED / f"{stem('bomb', cli, run)}-{name}.txt").write_text(text, encoding="utf-8")
        write_meta(f"{stem('bomb', cli, run)}.meta.json", meta)
        print(f"recorded recorded/{stem('bomb', cli, run)}*")
    return max(abs(c) for c in codes.values())


def print_bomb(cli, meta):
    arms = meta["arms"]
    base = arms["without"]["usage"]["total"]
    print(f"\n  token usage per arm, as reported ({NAMES[cli]} {meta['cli_version']}, {meta['model']}):")
    print(token_header(cli))
    for name, row in arms.items():
        print(token_row(cli, name, row["usage"], row["usage"]["total"] - base))
        if "init" in row:
            info = row["init"]
            print(f"        {info['tools']} tools in init, ToolSearch {'on' if info['tool_search_tool'] else 'off'}, "
                  f"bomb tools {len(info['bomb_tools'])}, answer {row['answer']!r}")
        else:
            print(f"        server required={row['server_required']}, answer {row['answer']!r}")


# ── Replay ───────────────────────────────────────────────────────────

def load_events(name):
    path = RECORDED / name
    if not path.is_file():
        raise Failure(f"no recording at recorded/{name}; make one with "
                      "`uv run agent_demo.py run <demo> --via <cli> --record`")
    return parse_lines(path.read_text(encoding="utf-8"))[0]


def load_meta(demo, cli, run):
    path = RECORDED / f"{stem(demo, cli, run)}.meta.json"
    if not path.is_file():
        raise Failure(f"no recording at recorded/{path.name}; make one with "
                      f"`uv run agent_demo.py run {demo} --via {cli} --record --run {run}`")
    return json.loads(path.read_text(encoding="utf-8"))


def replay_calls(events, cli):
    for call in tool_calls(events, cli):
        for line in describe_call(call, cli):
            print(line)
    answer = final_text(events, cli).strip()
    if answer:
        print("  done  " + answer.replace("\n", "\n        ")[:900])


def replay(demo, cli, run):
    meta = load_meta(demo, cli, run)
    print(f"replay {stem(demo, cli, run)}: {NAMES[cli]} ({cli}) {meta['cli_version']}, model {meta['model']} "
          f"({meta['model_source']}), effort {meta['effort']}, recorded {meta['started_at']}")
    print("No CLI is started and nothing touches the network; this is the recorded stream.")
    if demo == "loop":
        pre, post = meta["pre_state"], meta["post_state"]
        print(f"\n  pytest before the agent: {pre['pytest_summary']}")
        events = load_events(f"{stem(demo, cli, run)}.jsonl")
        replay_calls(events, cli)
        print(f"\n  pytest after the agent (run by the script): {post['pytest_summary']}")
        print(f"  files changed: {', '.join(post['changed_files']) or 'none'}")
        print("\n  token usage, as reported:")
        print(token_header(cli))
        print(token_row(cli, "loop", usage_counts(events, cli)))
    elif demo == "plan":
        for name, title in (("direct", "arm 1, straight to code"), ("plan", "arm 2a, plan only"),
                            ("build", "arm 2b, build the plan")):
            arm = meta["arms"][name]
            events = load_events(f"{stem(demo, cli, run)}-{name}.jsonl")
            print(f"\n── {title} ──")
            if name != "build":
                print(f"  pytest before: {arm['pre_state'].get('pytest_summary', 'not run')}")
            replay_calls(events, cli)
            if name == "plan":
                print(f"  plan source: {arm['plan_source']}; files changed by planning: "
                      f"{', '.join(arm['post_state']['changed_files']) or 'none'}")
            else:
                print(f"  pytest after (run by the script): {arm['post_state']['pytest_summary']}")
        print("\n  token usage per call, as reported:")
        print(token_header(cli))
        for name in ("direct", "plan", "build"):
            print(token_row(cli, name, usage_counts(load_events(f"{stem(demo, cli, run)}-{name}.jsonl"), cli)))
        print_comparison(cli, meta)
    else:
        for name in meta["arms"]:
            meta["arms"][name]["usage"] = usage_counts(load_events(f"{stem(demo, cli, run)}-{name}.jsonl"), cli)
        print_bomb(cli, meta)
        capture = "context" if cli == "claude" else "status"
        for phase in ("before", "after"):
            path = RECORDED / f"{stem(demo, cli, run)}-{capture}-{phase}.txt"
            if path.is_file():
                keep = [line for line in path.read_text(encoding="utf-8").splitlines()
                        if re.search(r"Tokens:|MCP tools|MCP server|System tools|Context window|context_bomb", line)]
                print(f"\n  /{capture} {phase} (recorded/{path.name}):")
                print("\n".join("    " + line.strip() for line in keep[:14]))
    return 0


# ── Command line ─────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(description="Act III agent demos: loop, plan first, context bomb.")
    sub = parser.add_subparsers(dest="action", required=True)
    for action, text in (("reset", "restore the demo's clean state and nothing else"),
                         ("run", "reset, then run the demo live with one CLI"),
                         ("replay", "play a recording: no CLI, no network")):
        command = sub.add_parser(action, help=text, description=text)
        command.add_argument("demo", choices=DEMOS)
        if action == "run":
            command.add_argument("--via", choices=CLIS, required=True, help="the harness to drive")
            command.add_argument("--record", action="store_true", help="write recorded/<demo>-<cli>-run<N>*")
        if action == "replay":
            command.add_argument("--via", choices=CLIS, default="claude", help="which recording (default claude)")
        if action in {"run", "replay"}:
            command.add_argument("--run", type=int, default=1, help="rehearsal number (default 1)")
        if action in {"reset", "run"}:
            command.add_argument("--work-root", default=str(DEFAULT_WORK_ROOT),
                                 help=f"where demo folders live (default {DEFAULT_WORK_ROOT})")
    args = parser.parse_args(argv)
    try:
        if args.action == "reset":
            reset(args.demo, Path(args.work_root))
            return 0
        if args.action == "replay":
            return replay(args.demo, args.via, args.run)
        check_login(args.via, args.demo)
        version = cli_version(args.via)
        print(f"using {args.via} ({version}); work root {args.work_root}")
        runner = {"loop": run_loop, "plan": run_plan, "bomb": run_bomb}[args.demo]
        return runner(args.via, args, version)
    except Failure as error:
        print(f"agent_demo.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
