"""Exercise the editor bootstrap through a real CLI with isolated extension state."""

from __future__ import annotations

import json
import sys

import pytest
from student_sandbox import REPO, Box

PINS = json.loads((REPO / "setup/editor.json").read_text(encoding="utf-8"))["extensions"]
CODE = '''#!{python}
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
with Path(os.environ['STUB_LOG']).open('a') as log:
    log.write('code ' + ' '.join(args) + '\\n')
state = Path(os.environ['STUB_EXTENSIONS'])
extensions = json.loads(state.read_text()) if state.exists() else {{}}
if '--locate-extension' in args:
    if os.environ.get('CODE_WSL_EXTENSION'):
        print('C:\\\\Users\\\\Student\\\\.vscode\\\\extensions\\\\ms-vscode-remote.remote-wsl-1.0.0')
elif '--list-extensions' in args:
    if os.environ.get('CODE_FAIL_LIST'):
        print('cannot connect to VS Code')
        raise SystemExit(7)
    print('Extensions installed in remote environment:')
    for name, version in extensions.items():
        print(name + '@' + version)
elif '--install-extension' in args:
    name, version = args[args.index('--install-extension') + 1].split('@')
    if os.environ.get('CODE_FAIL') == name:
        print('marketplace unavailable')
        raise SystemExit(8)
    if not os.environ.get('CODE_IGNORE_INSTALL'):
        extensions[name] = version
        state.write_text(json.dumps(extensions))
'''


def editor_box(tmp_path):
    box = Box(tmp_path)
    box.stub("code", CODE.format(python=sys.executable))
    box.env["STUB_EXTENSIONS"] = str(tmp_path / "extensions.json")
    return box


def command(box, *args):
    return [sys.executable, str(REPO / "setup/editor.py"), "--repo", str(box.root), *args]


def test_installs_exact_pins_once_and_verifies_a_rerun(tmp_path):
    box = editor_box(tmp_path)
    state = tmp_path / "extensions.json"
    state.write_text(json.dumps({"ms-python.python": "2020.1.0", "another.extension": "1.0.0"}))
    for _ in range(2):
        result = box.run(command(box))
        assert result.returncode == 0, result.stdout + result.stderr
        assert "verified all pinned VS Code extensions" in result.stdout
    actual = json.loads(state.read_text())
    assert actual == {**PINS, "another.extension": "1.0.0"}
    installs = [line for line in box.calls() if "--install-extension" in line]
    assert installs == [f"code --install-extension {name}@{version} --force" for name, version in PINS.items()]


def test_headless_setup_needs_no_editor_and_says_what_was_not_installed(tmp_path):
    box = Box(tmp_path)
    result = box.run(command(box))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no VS Code CLI found" in result.stdout and "extension installation was not run" in result.stdout
    assert not box.calls()


@pytest.mark.parametrize("failure", ["list", "install", "verification"])
def test_editor_failures_are_actionable_and_never_report_success(tmp_path, failure):
    box = editor_box(tmp_path)
    env = {"list": {"CODE_FAIL_LIST": "1"}, "install": {"CODE_FAIL": "astral-sh.ty"},
           "verification": {"CODE_IGNORE_INSTALL": "1"}}[failure]
    result = box.run(command(box), **env)
    assert result.returncode == 1
    assert "FAILED" in result.stdout and "rerun the setup command" in result.stdout
    assert "verified all pinned VS Code extensions" not in result.stdout
    assert {"list": "cannot connect", "install": "marketplace unavailable",
            "verification": "did not report the required installed versions"}[failure] in result.stdout


def test_manifest_is_validated_before_any_editor_command(tmp_path):
    box = editor_box(tmp_path)
    manifest = tmp_path / "invalid.json"
    manifest.write_text(json.dumps({"extensions": {"astral-sh.ty": "latest"}}))
    result = box.run(command(box, "--manifest", str(manifest)))
    assert result.returncode == 1 and "exact extension version" in result.stdout
    assert not box.calls()


def test_code_insiders_is_supported_when_stable_code_is_absent(tmp_path):
    box = editor_box(tmp_path)
    (box.bin / "code").rename(box.bin / "code-insiders")
    result = box.run(command(box))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "verified all pinned VS Code extensions" in result.stdout


def test_wsl_rejects_windows_only_pins_when_remote_wsl_is_missing(tmp_path):
    box = editor_box(tmp_path)
    box.stub("wslpath", "#!/bin/sh\nprintf '%s\\n' 'C:\\Programs\\VS Code\\bin\\code'\n")
    (tmp_path / "extensions.json").write_text(json.dumps(PINS))
    result = box.run(command(box), WSL_DISTRO_NAME="Ubuntu")
    assert result.returncode == 1
    assert "WSL extension is missing" in result.stdout and "Windows-only Python extensions" in result.stdout
    assert not [line for line in box.calls() if "--list-extensions" in line or "--install-extension" in line]


def test_wsl_windows_shim_can_install_after_the_wsl_extension_is_verified(tmp_path):
    box = editor_box(tmp_path)
    box.stub("wslpath", "#!/bin/sh\nprintf '%s\\n' 'C:\\Programs\\VS Code\\bin\\code'\n")
    result = box.run(command(box), WSL_DISTRO_NAME="Ubuntu", CODE_WSL_EXTENSION="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert box.calls()[0] == "code --locate-extension ms-vscode-remote.remote-wsl"
    assert "verified all pinned VS Code extensions" in result.stdout


def test_wsl_linux_cli_does_not_require_a_windows_extension(tmp_path):
    box = editor_box(tmp_path)
    box.stub("wslpath", "#!/bin/sh\nprintf '%s\\n' '\\\\wsl.localhost\\Ubuntu\\usr\\bin\\code'\n")
    result = box.run(command(box), WSL_DISTRO_NAME="Ubuntu")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not [line for line in box.calls() if "--locate-extension" in line]
