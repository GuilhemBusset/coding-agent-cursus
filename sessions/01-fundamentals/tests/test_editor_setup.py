"""Exercise the installed editor checker in a relocated course workspace, without VS Code."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import tomllib
from pathlib import Path
from typing import Any

import pytest

SESSION = Path(__file__).resolve().parents[1]
REPO = SESSION.parents[1]


def executable(environment: Path, name: str) -> Path:
    return environment / ("Scripts" if os.name == "nt" else "bin") / (name + (".exe" if os.name == "nt" else ""))


def run(argv: list[str], cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.fixture(scope="module")
def installed_workspace(tmp_path_factory):
    # A fresh path (including spaces) prevents the real checkout and an editor's saved
    # interpreter selection from supplying configuration or import paths by accident.
    repo = tmp_path_factory.mktemp("editor workspace ")
    session = repo / SESSION.relative_to(REPO)
    session.mkdir(parents=True)
    shutil.copyfile(REPO / "ty.toml", repo / "ty.toml")
    for name in ("pyproject.toml", "uv.lock", "README.md"):
        shutil.copyfile(SESSION / name, session / name)
    env = os.environ.copy()
    for name in ("PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT", "UV_PROJECT_ENVIRONMENT", "TY_CONFIG_FILE"):
        env.pop(name, None)
    env["XDG_CONFIG_HOME"] = str(repo / "empty-user-configuration")
    # This suite runs in the locked session environment, so its default packages are
    # already in uv's cache. The regression must work without another network request.
    sync = ["uv", "sync", "--locked", "--offline", "--python", sys.executable]
    run(sync, session, env)
    (repo / "setup").mkdir()
    run(["uv", "venv", "--offline", "--python", sys.executable, "setup/.venv"], repo, env)
    return repo, session, env, sync


def test_default_sync_preserves_the_pinned_editor_checker(installed_workspace):
    _, session, env, sync = installed_workspace
    config = tomllib.loads((session / "pyproject.toml").read_text(encoding="utf-8"))
    pin = next(dep.removeprefix("ty==") for dep in config["dependency-groups"]["typecheck"] if dep.startswith("ty=="))
    checker = executable(session / ".venv", "ty")
    assert checker.is_file(), "a default installation must include the editor's type checker"
    assert run([str(checker), "--version"], session, env).strip() == f"ty {pin}"
    run(sync, session, env)
    assert run([str(checker), "--version"], session, env).strip() == f"ty {pin}", (
        "a later ordinary uv sync must not remove the editor's pinned checker"
    )


class LanguageServer:
    """The small part of LSP needed to request real diagnostics over stdio."""

    def __init__(self, command: list[str], cwd: Path, env: dict[str, str]):
        self.process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        assert self.process.stdin is not None and self.process.stdout is not None
        self.stdin = self.process.stdin
        self.stdout = self.process.stdout
        self.messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.request_id = 0
        self.reader = threading.Thread(target=self.read_messages, daemon=True)
        self.reader.start()

    def read_messages(self) -> None:
        while True:
            headers = {}
            while True:
                line = self.stdout.readline()
                if not line:
                    self.messages.put(None)
                    return
                if line == b"\r\n":
                    break
                key, value = line.decode("ascii").split(":", 1)
                headers[key.lower()] = value.strip()
            self.messages.put(json.loads(self.stdout.read(int(headers["content-length"]))))

    def send(self, message: dict[str, Any]) -> None:
        payload = json.dumps({"jsonrpc": "2.0", **message}).encode("utf-8")
        self.stdin.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload)
        self.stdin.flush()

    def request(self, method: str, params: Any) -> Any:
        self.request_id += 1
        self.send({"id": self.request_id, "method": method, "params": params})
        while True:
            message = self.messages.get(timeout=15)
            assert message is not None, f"ty exited before answering {method}"
            if message.get("id") == self.request_id:
                assert "error" not in message, message
                return message["result"]

    def close(self) -> None:
        try:
            self.request("shutdown", None)
            self.send({"method": "exit", "params": None})
            self.process.wait(timeout=5)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
            self.reader.join(timeout=5)
            self.stdin.close()
            self.stdout.close()


def test_editor_reports_errors_in_each_project_and_resolves_session_packages(installed_workspace):
    repo, session, env, _ = installed_workspace
    workspace_path = REPO / "setup/cursus.code-workspace"
    workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
    projects = {REPO, *(path.parent for path in REPO.glob("sessions/*/pyproject.toml"))}
    configured = {(workspace_path.parent / folder["path"]).resolve() for folder in workspace["folders"]}
    assert projects <= configured, "every session needs a workspace folder for its own ty configuration"
    folders = [{"name": folder["name"], "uri": (repo / "setup" / folder["path"]).resolve().as_uri()}
               for folder in workspace["folders"]]
    assert {folder["uri"] for folder in folders} >= {repo.as_uri(), session.as_uri()}, (
        "the course workspace must expose each project to the language server"
    )
    checker = executable(session / ".venv", "ty")
    client = LanguageServer([str(checker), "server"], repo, env)
    try:
        client.request("initialize", {
            "processId": None,
            "capabilities": {"textDocument": {"diagnostic": {"dynamicRegistration": False}}},
            "workspaceFolders": folders,
        })
        client.send({"method": "initialized", "params": {}})
        probes = {
            repo / "setup/student/editor_probe.py": 'answer: int = "wrong"\n',
            session / "exercises/editor_probe.py": (
                "import highspy\nimport pytest\nmodel: highspy.Highs = 1\nexpected = pytest.approx(1.0)\n"
            ),
        }
        for path, source in probes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            client.send({"method": "textDocument/didOpen", "params": {"textDocument": {
                "uri": path.as_uri(), "languageId": "python", "version": 1, "text": source,
            }}})
            diagnostics = client.request("textDocument/diagnostic", {"textDocument": {"uri": path.as_uri()}})
            codes = [item["code"] for item in diagnostics["items"]]
            assert codes == ["invalid-assignment"], diagnostics
    finally:
        client.close()
