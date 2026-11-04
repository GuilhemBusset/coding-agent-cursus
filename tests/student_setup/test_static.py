"""Static checks on the student setup: shellcheck, Bash 3.2 and Windows PowerShell 5.1 syntax,
the floors against the setup check's, and each track's status in the docs against the record."""

from __future__ import annotations

import ast
import re
import subprocess

import prepare
from student_sandbox import REPO, STUDENT, powershell

SHELL = [STUDENT / "install.sh", REPO / "setup/session-01-fundamentals.sh",
         REPO / "tests/student_setup/run_twice.sh", REPO / "tests/student_setup/linux_container.sh",
         REPO / "tests/student_setup/run_local.sh"]
POWERSHELL = [STUDENT / "install.ps1", REPO / "tests/student_setup/run_twice.ps1"]
# The parser check of Session 1's test_ps51_syntax_and_launch_contract: tokens, so 7-only syntax
# in comments is not rejected, and AST types for ternary and null-conditional expressions.
PS51 = r'''
$tokens = $null; $errors = $null
$tree = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
$bad = @($tree.FindAll({param($n) $n.GetType().Name -match 'TernaryExpressionAst|PipelineChainAst' -or ($n.PSObject.Properties['NullConditional'] -and $n.NullConditional)}, $true))
$badTokens = @($tokens | Where-Object { $_.Kind.ToString() -in @('AndAnd','OrOr','QuestionQuestion','QuestionQuestionEquals','QuestionDot') -or ($_.Kind.ToString() -eq 'Variable' -and $_.Text -match '^\$IsWindows$') })
$parallel = @($tree.FindAll({param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.GetCommandName() -in @('ForEach-Object','%') -and @($n.CommandElements | Where-Object { $_ -is [System.Management.Automation.Language.CommandParameterAst] -and $_.ParameterName -eq 'Parallel' }).Count -gt 0}, $true))
if (@($errors).Count -gt 0 -or $bad.Count -gt 0 -or $badTokens.Count -gt 0 -or $parallel.Count -gt 0) { exit 1 }
'''
# Bash 4+ only: associative arrays, case conversion, mapfile/readarray, namerefs, `;&`, `|&`.
BASH4 = re.compile(r"\b(?:declare|local|typeset)\s+-[a-zA-Z]*[An]|\$\{\w+(?:,,?|\^\^?)\}|\b(?:mapfile|readarray|coproc)\b|;;?&|\|&")


def code_lines(path):
    return [line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")]


def test_shell_scripts_pass_pinned_shellcheck():
    result = subprocess.run(["uv", "run", "--no-project", "--with", "shellcheck-py==0.10.0.1", "shellcheck",
                             *map(str, SHELL)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr


def test_install_sh_has_no_bash_4_syntax():
    for path in (STUDENT / "install.sh", REPO / "tests/student_setup/run_twice.sh"):
        bad = [line for line in code_lines(path) if BASH4.search(line)]
        assert bad == [], f"{path.name} must run on Bash 3.2 (macOS /bin/bash): {bad}"


def test_powershell_scripts_parse_as_windows_powershell_5_1():
    for path in POWERSHELL:
        assert path.read_bytes().isascii(), f"{path.name}: Windows PowerShell 5.1 reads a BOM-less file as ANSI"
        command = "$path = '" + str(path).replace("'", "''") + "'\n" + PS51
        result = subprocess.run([powershell(), "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, f"{path.name}: parser errors or PowerShell 7-only syntax"


def test_installer_floors_equal_the_setup_checks_floors():
    check = prepare.latest_check(prepare.sessions(REPO))
    assert check is not None
    tree = ast.parse(check.read_text(encoding="utf-8"))
    floors = next(ast.literal_eval(node.value) for node in ast.walk(tree) if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "FLOORS" for t in node.targets))
    pinned = {}
    for line in (STUDENT / "versions.env").read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.endswith("_FLOOR"):
            pinned[key[:-len("_FLOOR")].lower()] = tuple(int(x) for x in value.split("."))
    assert pinned == floors, f"versions.env floors {pinned} differ from FLOORS in {check}"
    # The scripts read the floors from versions.env and never repeat them.
    for path in (STUDENT / "install.sh", STUDENT / "install.ps1"):
        text = "\n".join(code_lines(path))
        for value in floors.values():
            assert ".".join(map(str, value)) not in text, f"{path.name} hard-codes a floor"


def statuses_in_record():
    record = (STUDENT / "verification.md").read_text(encoding="utf-8")
    section = record.split("## Track status", 1)[1].split("\n## ", 1)[0]
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in section.splitlines()
            if line.startswith("|") and not re.match(r"\|\s*(Track|-)", line)]
    return {row[0]: (row[1], row[2]) for row in rows}


def statuses_in_docs():
    docs = (STUDENT / "README.md").read_text(encoding="utf-8")
    found = {}
    for heading, body in re.findall(r"^### ([^\n]+)\n(.*?)(?=^##)", docs + "\n##", re.M | re.S):
        match = re.search(r"^\*\*Status:\*\* CI: (.+?)\. Live run: (.+?)\.", body, re.M)
        if match:
            found[heading.strip()] = (match[1], match[2])
    return found


def test_each_tracks_status_in_the_docs_matches_the_verification_record():
    record, docs = statuses_in_record(), statuses_in_docs()
    tracks = {"Windows (PowerShell)", "Windows with WSL 2", "macOS", "Debian / Ubuntu", "Fedora", "Arch", "Other Linux"}
    assert set(record) == tracks and set(docs) == tracks, (sorted(record), sorted(docs))
    for track, (ci, live) in record.items():
        assert ci in {"tested in CI", "not in CI"} and live in {"tested live", "untested"}, (track, ci, live)
        assert docs[track] == (ci, live), f"{track}: the README says {docs[track]}, the record {(ci, live)}"
