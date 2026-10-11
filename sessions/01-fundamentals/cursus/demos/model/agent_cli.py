"""Shared plumbing for the Act I demos: find a logged-in agent CLI and call it headless.

Both demos drive Claude Code (`claude -p`) or Codex (`codex exec`) with the CLI's own
login. Nothing here reads an API key. Imported by strawberry.py and sampling.py, which
`uv run` puts next to it on the import path.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
RECORDED = HERE / "recorded"
WORK = HERE / "work"

CLIS = ("claude", "codex")
# Small, fast models at low effort: the point is the failure mode, not the best score.
MODELS = {"claude": "claude-haiku-5-5", "codex": "gpt-6-luna"}
EFFORT = {"claude": "low", "codex": "low"}
NAMES = {"claude": "Claude Code", "codex": "Codex"}
LOGIN = {"claude": "run `claude` and type /login", "codex": "run `codex login`"}
TIMEOUT_S = 300
PRIVATE_KEYS = {"session_id", "thread_id", "uuid"}
PRIVATE_LINES = re.compile(r"(?m)^session id:.*\n?")
BANNER_MODEL = re.compile(r"(?m)^\s*model:\s*\S+\s*$")
CLAUDE_RESULT_KEYS = ("type", "subtype", "is_error", "num_turns", "result", "stop_reason",
                      "duration_ms", "modelUsage")
AUTH_ERROR = re.compile(r"not logged in|log ?in|logged out|auth|api key|credential|401|403", re.I)


class Failure(Exception):
    """A user-facing error: printed as is, without a traceback."""


def replay_command(script, via=None, pivot=False):
    return (f"uv run --offline {script} --replay" + (" --pivot" if pivot else "")
            + (f" --via {via}" if via else ""))


def headless_argv(cli, prompt, last_message=None):
    """One answer, no tools: Claude Code with --tools "", Codex read-only without a shell."""
    if cli == "claude":
        return ["claude", "-p", prompt, "--model", MODELS[cli], "--effort", EFFORT[cli],
                "--tools", "", "--strict-mcp-config", "--no-session-persistence",
                "--output-format", "json"]
    return ["codex", "exec", "--sandbox", "read-only", "-m", MODELS[cli],
            "-c", f'model_reasoning_effort="{EFFORT[cli]}"', "--disable", "shell_tool",
            "--disable", "unified_exec", "--skip-git-repo-check", "--ephemeral",
            "-o", last_message or "<last-message-file>", prompt]


def shown_command(argv, prompt):
    """The argv as recorded: the prompt and the temporary file are placeholders."""
    shown, previous = [], None
    for arg in argv:
        if arg == prompt:
            shown.append("<prompt>")
        elif previous in {"-o", "--output-last-message"}:
            shown.append("<last-message-file>")
        else:
            shown.append(arg)
        previous = arg
    return shown


def _status(argv):
    try:
        done = subprocess.run(argv, cwd=HERE, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    return done.returncode, done.stdout + done.stderr


def login_state(cli):
    """'ok', 'logged-out' or 'unknown' (this version has no status subcommand)."""
    code, text = _status(["claude", "auth", "status"] if cli == "claude" else ["codex", "login", "status"])
    try:
        reported = json.loads(text).get("loggedIn")
    except (ValueError, AttributeError):
        reported = None
    if reported is False or re.search(r"not logged in|logged out", text, re.I):
        return "logged-out"
    if code == 0:
        return "ok"
    if reported is True:
        return "ok"
    return "unknown"


def probe(cli):
    """Fallback when the CLI cannot report its login: one tiny prompt, auth errors mean logged out."""
    with tempfile.TemporaryDirectory() as scratch:
        argv = headless_argv(cli, "Reply with OK only.", str(Path(scratch) / "last.txt"))
        try:
            done = subprocess.run(argv, cwd=HERE, stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S,
                                  check=False)
        except (OSError, subprocess.TimeoutExpired):
            return "broken"
    failed = done.returncode != 0
    if cli == "claude":
        results = [e for e in parse_events(done.stdout) if e.get("type") == "result"]
        failed = failed or not results or bool(results[-1].get("is_error"))
    if not failed:
        return "ok"
    return "logged-out" if AUTH_ERROR.search(done.stdout + done.stderr) else "broken"


def describe(cli, state):
    if state == "missing":
        return (f"{cli}: not installed (not found on PATH); install {NAMES[cli]}, "
                f"then {LOGIN[cli]}")
    if state == "logged-out":
        return f"{cli}: installed but not logged in; {LOGIN[cli]}"
    return f"{cli}: installed but did not answer a test prompt; run it once by hand to see why"


def pick(via, script, pivot=False):
    """The CLI to use: --via forces one; otherwise the first installed and logged-in one."""
    reasons = {}
    for cli in ([via] if via else CLIS):
        if shutil.which(cli) is None:
            reasons[cli] = "missing"
            continue
        state = login_state(cli)
        if state == "unknown":
            state = probe(cli)
        if state == "ok":
            skipped = "".join(f"; {other} {reasons[other].replace('-', ' ')}" for other in reasons)
            how = "--via" if via else "first installed and logged-in CLI" + skipped
            print(f"using {cli} ({how})", flush=True)
            return cli
        reasons[cli] = state
    lines = [f"no usable agent CLI{f' for --via {via}' if via else ''}:"]
    lines += [f"  {describe(cli, state)}" for cli, state in reasons.items()]
    if via:
        lines.append(f"Or replay the recording: {replay_command(script, via, pivot)}")
    else:
        lines.append(f"Or replay the recording: {replay_command(script, pivot=pivot)}"
                     f" (add --via codex for the Codex one)")
    raise Failure("\n".join(lines))


def cli_failed(cli, code, output, script, pivot=False):
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    detail = f" ({lines[-1][:120]})" if lines else ""
    hint = f"; {LOGIN[cli]}" if AUTH_ERROR.search(output) else ""
    return Failure(f"{cli} exited with status {code}{detail}{hint}\n"
                   f"Or replay the recording: {replay_command(script, cli, pivot)}")


def run(cli, argv, script, env=None, pivot=False):
    """Run one CLI call; stdout and stderr, or a Failure that points to the replay."""
    try:
        done = subprocess.run(argv, cwd=HERE, stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", env=env,
                              timeout=TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Failure(f"{cli} could not run ({type(error).__name__})\n"
                      f"Or replay the recording: {replay_command(script, cli, pivot)}") from None
    if done.returncode != 0:
        raise cli_failed(cli, done.returncode, done.stderr + done.stdout, script, pivot)
    return done.stdout, done.stderr


def ask_once(cli, prompt, script):
    """One headless, tool-free answer. Returns (answer, kept CLI output for the recording)."""
    if cli == "claude":
        stdout, _ = run(cli, headless_argv(cli, prompt), script)
        events = [{key: e[key] for key in CLAUDE_RESULT_KEYS if key in e}
                  for e in parse_events(stdout) if e.get("type") == "result"]
        if not events or events[-1].get("is_error"):
            detail = events[-1].get("result", "") if events else stdout.strip()[:120]
            raise Failure(f"claude returned an error ({detail})\n"
                          f"Or replay the recording: {replay_command(script, cli)}")
        return str(events[-1].get("result", "")).strip(), scrub(events)
    with tempfile.TemporaryDirectory() as scratch:
        last = Path(scratch) / "last-message.txt"
        _, stderr = run(cli, headless_argv(cli, prompt, str(last)), script)
        message = last.read_text(encoding="utf-8") if last.is_file() else ""
    return message.strip(), {"transcript": scrub_transcript(stderr), "last_message": message}


def parse_events(text):
    """CLI stdout as a list of JSON objects (one document or JSON lines)."""
    try:
        value = json.loads(text)
        found = value if isinstance(value, list) else [value]
    except ValueError:
        found = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    found.append(json.loads(line))
                except ValueError:
                    continue
    return [event for event in found if isinstance(event, dict)]


def scrub(value):
    """Drop private ids and make paths relative to this folder or the home folder."""
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items() if key not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        value = value.replace(str(HERE) + "/", "").replace(str(HERE), ".")
        return value.replace(str(Path.home()), "~")
    return value


def scrub_transcript(text):
    return scrub(PRIVATE_LINES.sub("", text))


def banner_lines(transcripts):
    """Codex's verbatim `model: <id>` config-banner lines, in order, without repeats."""
    lines = []
    for text in transcripts:
        for match in BANNER_MODEL.finditer(text):
            line = match[0].strip()
            if line not in lines:
                lines.append(line)
    return lines


def reported_models(cli, kept):
    """Model IDs as the CLI itself reported them in the kept output."""
    if cli == "codex":
        return sorted({line.split(":", 1)[1].strip() for line in kept})
    found = set()

    def walk(value):
        if isinstance(value, dict):
            if value.get("type") == "result":
                found.update((value.get("modelUsage") or {}).keys())
            if value.get("type") == "assistant":
                model = (value.get("message") or {}).get("model")
                if isinstance(model, str):
                    found.add(model)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(kept)
    return sorted(found)


def cli_version(cli):
    try:
        done = subprocess.run([cli, "--version"], cwd=HERE, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return done.stdout.strip() or "unknown"


def load(name, script):
    path = RECORDED / name
    if not path.is_file():
        raise Failure(f"no recording at recorded/{name}; make one with `uv run {script} --record`")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def codex_env():
    """Codex's workspace-write sandbox cannot write uv's default cache, so give it one in work/."""
    return dict(os.environ, UV_CACHE_DIR=str(WORK / ".uv-cache"))
