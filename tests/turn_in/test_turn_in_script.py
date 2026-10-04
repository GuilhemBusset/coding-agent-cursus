"""Offline acceptance contracts for issue 22; run with the pinned uv/pytest command.

Only gh and sleep are fakes. Git, hooks, commits, URL rewriting, and bare
receivers are real. GIT_ALLOW_PROTOCOL=file makes accidental network access fail.
Live agent invocation and GitHub ruleset enforcement remain owner evidence.
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/turn-in.sh"


def command(args, *, cwd, env=None, ok=True):
    result = subprocess.run(
        [str(a) for a in args], cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40,
    )
    if ok:
        assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result


def write(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


# Interpret --jq with the real jq, rather than recognizing particular query text.
# Unknown gh operations fail closed, so a typo cannot look like a successful API call.
FAKE_GH = r'''#!/usr/bin/env bash
set -euo pipefail
argv=$(jq -cn --args '$ARGS.positional' -- "$@")
query=''; fields=''; method=GET; input=''; positional=()
while (($#)); do
  case "$1" in
    --jq|-q) query=$2; shift 2 ;;
    --json) fields=$2; shift 2 ;;
    --method|-X) method=$2; shift 2 ;;
    --input) input=$2; shift 2 ;;
    --paginate|--clone=false) shift ;;
    *) positional+=("$1"); shift ;;
  esac
done
payload=null
if [[ -n "$input" ]]; then payload=$(cat "$input"); fi
jq -cn --argjson args "$argv" --argjson payload "$payload" \
  '{args:$args,payload:$payload}' >> "$GH_LOG"
emit() {
  if [[ -n "$query" ]]; then jq -r "$query"; else cat; fi
}
normalize() {
  local value=$1
  value=${value#https://github.com/}; value=${value#ssh://git@github.com/}
  value=${value#git@github.com:}; printf '%s' "${value%.git}"
}
case "${positional[0]-} ${positional[1]-}" in
  'auth status') exit 0 ;;
  'api user') jq '{login:.login}' "$GH_STATE" | emit ;;
  'repo view')
    repo=$(normalize "${positional[2]-$(jq -r .origin "$GH_STATE")}")
    if [[ $(jq -r '.view_failure // false' "$GH_STATE") == true ]]; then exit 41; fi
    data=$(jq -ce --arg repo "$repo" '.repos[$repo]' "$GH_STATE")
    if [[ -n "$fields" ]]; then
      data=$(printf '%s' "$data" | jq --arg fields "$fields" \
        'with_entries(select(.key as $k | $fields | split(",") | index($k)))')
    fi
    printf '%s\n' "$data" | emit ;;
  'repo fork')
    [[ $(jq -r '.fork_failure // false' "$GH_STATE") != true ]] || exit 42
    printf '%s\n' '{}' ;;
  api\ *)
    endpoint=${positional[1]#/}
    case "$endpoint" in
      repos/*/forks) jq '.forks' "$GH_STATE" | emit ;;
      repos/*/rulesets|repos/*/rulesets/*)
        if [[ $(jq -r '.rules_failure // ""' "$GH_STATE") == "$method" ]]; then exit 43; fi
        if [[ "$method" == GET ]]; then
          jq '.rulesets // []' "$GH_STATE" | emit
        else
          printf '%s\n' '{"id":999}'
        fi ;;
      *) echo "Unexpected gh endpoint: $endpoint" >&2; exit 90 ;;
    esac ;;
  *) echo "Unexpected gh call: $argv" >&2; exit 91 ;;
esac
'''


def isolated_environment(tmp_path):
    """Reusable by the ruleset tests; never reads real gh credentials or Git config."""
    assert shutil.which("git"), "git is a prerequisite"
    assert shutil.which("jq"), "real jq is a prerequisite (not mocked)"
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GIT_", "GH_", "GITHUB_"))}
    bindir = tmp_path / "bin"
    bindir.mkdir()
    env.update({
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "file", "GIT_EDITOR": "true",
        "GIT_AUTHOR_NAME": "Acceptance Student", "GIT_AUTHOR_EMAIL": "student@example.invalid",
        "GIT_COMMITTER_NAME": "Acceptance Student", "GIT_COMMITTER_EMAIL": "student@example.invalid",
        "GH_CONFIG_DIR": str(tmp_path / "gh-config"), "GH_PROMPT_DISABLED": "1",
        "GH_STATE": str(tmp_path / "gh-state.json"), "GH_LOG": str(tmp_path / "gh.jsonl"),
        "REAL_GIT": shutil.which("git"), "GIT_LOG": str(tmp_path / "git.jsonl"),
        "SLEEP_LOG": str(tmp_path / "sleep.jsonl"), "LC_ALL": "C",
    })
    write(bindir / "gh", FAKE_GH, executable=True)
    write(bindir / "git", '''#!/usr/bin/env bash
set -euo pipefail
jq -cn --args '$ARGS.positional' -- "$@" >> "$GIT_LOG"
exec "$REAL_GIT" "$@"
''', executable=True)
    write(bindir / "sleep", '''#!/usr/bin/env bash
jq -cn --args '$ARGS.positional' -- "$@" >> "$SLEEP_LOG"
''', executable=True)
    return env


class Sandbox:
    def __init__(self, path, *, nn="01", handle="stud", default="main",
                 permission="WRITE", fork_origin=False, scheme="https"):
        self.path, self.nn, self.handle, self.default = path, nn, handle, default
        self.env = isolated_environment(path)
        self.exercises = f"sessions/{nn}-fundamentals/exercises"
        self.branch = f"homework/s{nn}/{handle}"
        self.course = "course/cursus"
        self.fork_name = f"{handle}/cursus-1"
        self.scheme = scheme
        self.origin = self.fork_name if fork_origin else self.course
        self.state = {
            "login": handle, "origin": self.origin,
            "repos": {
                self.course: {"nameWithOwner": self.course, "parent": None,
                              "viewerPermission": permission,
                              "defaultBranchRef": {"name": default}},
                self.fork_name: {"nameWithOwner": self.fork_name,
                                 "parent": {"nameWithOwner": self.course},
                                 "viewerPermission": "ADMIN",
                                 "defaultBranchRef": {"name": default}},
            },
            "forks": [{"owner": {"login": handle}, "full_name": self.fork_name}],
        }
        self.save()
        seed = path / "seed"
        self.git("init", "-b", default, seed, cwd=path)
        write(seed / "README.md", "course baseline\n")
        write(seed / "outside.txt", "outside baseline\n")
        write(seed / self.exercises / "answer.txt", "initial answer\n")
        write(seed / self.exercises / "delete-me.txt", "obsolete\n")
        write(seed / "sessions/08-other/exercises/other.txt", "other session\n")
        shutil.copytree(ROOT / ".githooks", seed / ".githooks")
        for hook in (seed / ".githooks").iterdir():
            hook.chmod(0o755)
        self.git("add", ".", cwd=seed)
        self.git("commit", "-m", "Course baseline", cwd=seed)
        self.base = self.git("rev-parse", "HEAD", cwd=seed).stdout.strip()
        self.remotes = {}
        for name, slug in [(self.course, "course"), (self.fork_name, "fork"),
                           ("unrelated/elsewhere", "unrelated")]:
            bare = path / f"{slug}.git"
            self.git("clone", "--bare", seed, bare, cwd=path)
            self.remotes[name] = bare
            for url in (f"https://github.com/{name}", f"git@github.com:{name}",
                        f"ssh://git@github.com/{name}"):
                self.git("config", "--global", "--add", f"url.{bare}.insteadOf", url + ".git", cwd=path)
                self.git("config", "--global", "--add", f"url.{bare}.insteadOf", url, cwd=path)
        self.repo = path / "student"
        self.git("clone", self.url(self.origin), self.repo, cwd=path)
        self.git("config", "core.hooksPath", ".githooks")
        self.git("config", "commit.gpgSign", "false")
        self.git("config", "push.default", "matching")
        # An explicit homework refspec must override this hostile inherited setting.
        self.git("config", "remote.origin.push", "HEAD:refs/heads/main")
        self.clear_logs()

    def url(self, name):
        prefix = "https://github.com/" if self.scheme == "https" else "git@github.com:"
        return f"{prefix}{name}.git"

    def save(self):
        write(Path(self.env["GH_STATE"]), json.dumps(self.state))

    def git(self, *args, cwd=None, ok=True):
        return command([self.env["REAL_GIT"], *args],
                       cwd=cwd or self.repo, env=self.env, ok=ok)

    def clear_logs(self):
        for key in ("GH_LOG", "GIT_LOG", "SLEEP_LOG"):
            write(Path(self.env[key]), "")

    def refs(self):
        return {name: self.git("for-each-ref", "--format=%(refname) %(objectname)", cwd=bare).stdout
                for name, bare in self.remotes.items()}

    def tip(self, repo=None):
        return self.git("rev-parse", f"refs/heads/{self.branch}",
                        cwd=self.remotes[repo or self.course]).stdout.strip()

    def edit(self, relative="answer.txt", content="student's solution\n"):
        write(self.repo / self.exercises / relative, content)

    def run(self, *args, cwd=None, success=True):
        assert SCRIPT.is_file(), "D1: scripts/turn-in.sh must exist"
        self.save()
        self.clear_logs()
        before_defaults = {name: self.git("rev-parse", self.default, cwd=bare).stdout
                           for name, bare in self.remotes.items()}
        result = command(["bash", SCRIPT, *args], cwd=cwd or self.repo,
                         env=self.env, ok=False)
        for name, bare in self.remotes.items():
            assert self.git("rev-parse", self.default, cwd=bare).stdout == before_defaults[name]
        calls = records(Path(self.env["GIT_LOG"]))
        for args_seen in calls:
            assert not any(a == "--no-verify" or a.startswith("--force") for a in args_seen), args_seen
            if "push" in args_seen:
                assert "-f" not in args_seen, args_seen
                assert not any(a.startswith("+") for a in args_seen), args_seen
                assert not any("refs/heads/main" in a or "refs/heads/master" in a for a in args_seen), args_seen
                assert f"HEAD:refs/heads/{self.branch}" in args_seen, args_seen
        assert self.git("config", "--get", "core.hooksPath").stdout.strip() == ".githooks"
        if success:
            assert result.returncode == 0, (result.stdout, result.stderr)
        else:
            assert result.returncode != 0, "Expected a refusal, but the script succeeded"
            assert (result.stdout + result.stderr).strip(), "Refusals must explain the problem"
        return result

    def pushed_paths(self, repo=None):
        return self.git("diff", "--name-only", f"{self.base}...{self.tip(repo)}",
                        cwd=self.remotes[repo or self.course]).stdout.splitlines()

    def assert_confined(self, repo=None):
        assert all(p.startswith(self.exercises + "/") for p in self.pushed_paths(repo))

    def assert_no_push(self):
        assert not any("push" in args for args in records(Path(self.env["GIT_LOG"])))

    def advance_remote(self, *, outside=False):
        """Create a realistic submission from a second student's clone."""
        peer = self.path / "peer"
        self.git("clone", self.remotes[self.course], peer, cwd=self.path)
        remote_branch = self.git("show-ref", "--verify", f"refs/remotes/origin/{self.branch}",
                                 cwd=peer, ok=False)
        start = f"origin/{self.branch}" if remote_branch.returncode == 0 else self.default
        self.git("checkout", "-b", self.branch, start, cwd=peer)
        write(peer / ("README.md" if outside else f"{self.exercises}/remote.txt"), "peer edit\n")
        self.git("add", ".", cwd=peer)
        self.git("commit", "-m", "Previous submission", cwd=peer)
        self.git("push", "origin", f"HEAD:refs/heads/{self.branch}", cwd=peer)
        return self.tip()

    def advance_course_default(self):
        peer = self.path / "course-maintainer"
        self.git("clone", self.remotes[self.course], peer, cwd=self.path)
        write(peer / "README.md", "new course baseline\n")
        self.git("add", "README.md", cwd=peer)
        self.git("commit", "-m", "Course update", cwd=peer)
        self.git("push", "origin", f"HEAD:refs/heads/{self.default}", cwd=peer)
        self.base = self.git("rev-parse", "HEAD", cwd=peer).stdout.strip()
        return self.base


class TestSubmission:
    @pytest.mark.parametrize("nn,handle,default,permission", [
        ("01", "stud", "main", "WRITE"),
        ("04", "Ada-73", "trunk", "MAINTAIN"),
    ])
    def test_add_modify_delete_from_session_and_repeat(self, tmp_path, nn, handle, default, permission):
        s = Sandbox(tmp_path, nn=nn, handle=handle, default=default, permission=permission)
        s.edit()
        s.edit("nested/with spaces.txt", "new solution\n")
        (s.repo / s.exercises / "delete-me.txt").unlink()
        result = s.run(nn, cwd=s.repo / f"sessions/{nn}-fundamentals")
        tip = s.tip()
        assert s.git("show", "-s", "--format=%P", tip).stdout.strip() == s.base
        assert s.git("show", "-s", "--format=%s", tip).stdout.strip() == f"Turn in session {nn} homework ({handle})"
        assert f"https://github.com/course/cursus/tree/{s.branch}" in result.stdout
        assert any(r["args"][:2] == ["api", "user"] for r in records(Path(s.env["GH_LOG"])))
        assert set(s.pushed_paths()) == {f"{s.exercises}/{p}" for p in
                                        ("answer.txt", "delete-me.txt", "nested/with spaces.txt")}
        assert s.git("show", f"{tip}:{s.exercises}/answer.txt").stdout == "student's solution\n"
        assert s.git("status", "--porcelain").stdout == ""
        for changed in (True, False):
            if changed:
                s.edit(content="revised solution\n")
            s.run(nn)
            new_tip = s.tip()
            assert new_tip != tip
            assert s.git("show", "-s", "--format=%P", new_tip).stdout.strip() == tip
            assert s.git("rev-list", "--count", f"{tip}..{new_tip}").stdout.strip() == "1"
            if not changed:
                assert s.git("diff", "--name-only", tip, new_tip).stdout == ""
            s.assert_confined()
            tip = new_tip

    def test_remote_only_branch_is_reused(self, tmp_path):
        s = Sandbox(tmp_path)
        old = s.advance_remote()
        s.edit()
        s.run("01")
        assert s.git("rev-parse", "HEAD^").stdout.strip() == old
        assert s.git("show", f"HEAD:{s.exercises}/remote.txt").stdout == "peer edit\n"
        s.assert_confined()

    def test_new_branch_uses_fresh_course_default_not_stale_head(self, tmp_path):
        s = Sandbox(tmp_path)
        course_tip = s.advance_course_default()
        assert s.git("rev-parse", "HEAD").stdout.strip() != course_tip
        s.edit()
        s.run("01")
        assert s.git("rev-parse", "HEAD^").stdout.strip() == course_tip
        assert s.git("show", "HEAD:README.md").stdout == "new course baseline\n"
        s.assert_confined()

    def test_local_branch_behind_remote_fast_forwards(self, tmp_path):
        s = Sandbox(tmp_path)
        s.edit()
        s.run("01")
        old = s.advance_remote()
        s.run("01")
        assert s.git("rev-parse", "HEAD^").stdout.strip() == old
        s.assert_confined()

    @pytest.mark.parametrize("passes", [True, False])
    def test_session_check_gates_commit_and_push_and_uses_session_cwd(self, tmp_path, passes):
        s = Sandbox(tmp_path)
        s.edit()
        marker = tmp_path / "check-cwd.txt"
        s.env["CHECK_MARKER"] = str(marker)
        s.edit("turn-in-check.sh", '#!/usr/bin/env bash\npwd > "$CHECK_MARKER"\n'
               'test -f exercises/answer.txt || exit 66\n' + ("exit 0\n" if passes else "exit 17\n"))
        before, refs = s.git("rev-parse", "HEAD").stdout, s.refs()
        s.run("01", success=passes)
        assert marker.read_text().strip() == str(s.repo / "sessions/01-fundamentals")
        if passes:
            assert s.tip() != before.strip()
        else:
            assert s.git("rev-parse", "HEAD").stdout == before
            assert s.refs() == refs
            s.assert_no_push()

    @pytest.mark.parametrize("failures,success", [(1, True), (9, False)])
    def test_push_retry_is_bounded(self, tmp_path, failures, success):
        s = Sandbox(tmp_path)
        s.edit()
        counter = tmp_path / "receive-count"
        s.env["RECEIVE_COUNT"] = str(counter)
        write(s.remotes[s.course] / "hooks/pre-receive", f'''#!/usr/bin/env bash
set -eu
n=0
if test -f "$RECEIVE_COUNT"; then n=$(cat "$RECEIVE_COUNT"); fi
n=$((n+1)); echo "$n" > "$RECEIVE_COUNT"
if test "$n" -le {failures}; then echo 'transient receiver failure' >&2; exit 1; fi
cat >/dev/null
''', executable=True)
        refs = s.refs()
        s.run("01", success=success)
        assert counter.read_text().strip() == ("2" if success else "4")
        assert records(Path(s.env["SLEEP_LOG"])) == ([["2"]] if success else [["2"], ["4"], ["8"]])
        if success:
            s.assert_confined()
            assert s.git("rev-list", "--count", f"{s.base}..HEAD").stdout.strip() == "1"
        else:
            assert s.refs() == refs
            assert not any(r["args"][:2] == ["repo", "fork"] for r in records(Path(s.env["GH_LOG"])))

    def test_no_force_or_hook_bypass_in_script(self):
        # Comments may explain the prohibition; executable lines may not use it.
        source = "\n".join(line for line in SCRIPT.read_text().splitlines()
                           if not line.lstrip().startswith("#"))
        assert not re.search(r"--force(?:-with-lease)?\b|--no-verify\b|\+refs/", source)
        assert not re.search(r"\bgit\s+push[^\n]*\s-f(?:\s|$)", source)


class TestForkFallback:
    @pytest.mark.parametrize("scheme", ["https", "ssh"])
    def test_read_permission_uses_actual_fork_and_ignores_named_remote(self, tmp_path, scheme):
        s = Sandbox(tmp_path, permission="READ", scheme=scheme)
        s.git("remote", "add", "fork", s.url("unrelated/elsewhere"))
        before = s.refs()
        s.edit()
        result = s.run("01")
        after = s.refs()
        assert before[s.course] == after[s.course]
        assert before["unrelated/elsewhere"] == after["unrelated/elsewhere"]
        assert before[s.fork_name] != after[s.fork_name]
        s.assert_confined(s.fork_name)
        assert f"https://github.com/{s.fork_name}/tree/{s.branch}" in result.stdout
        assert f"https://github.com/{s.course}/compare/main...stud:{s.branch}" in result.stdout
        calls = [r["args"] for r in records(Path(s.env["GH_LOG"]))]
        assert any(c[:2] == ["repo", "fork"] and s.course in c and "--clone=false" in c for c in calls)
        assert any(f"repos/{s.course}/forks" in c and "--paginate" in c for c in calls)
        pushes = [c for c in records(Path(s.env["GIT_LOG"])) if "push" in c]
        assert pushes and all(s.url(s.fork_name) in c or s.url(s.fork_name).removesuffix(".git") in c
                              for c in pushes)

    @pytest.mark.parametrize("default", ["main", "trunk"])
    def test_origin_itself_is_a_fork(self, tmp_path, default):
        s = Sandbox(tmp_path, fork_origin=True, default=default)
        # The course may have advanced beyond both the fork and the clone.
        course_tip = s.advance_course_default()
        before = s.refs()
        s.edit()
        result = s.run("01")
        assert s.refs()[s.course] == before[s.course]
        assert s.tip(s.fork_name) != s.base
        assert s.git("rev-parse", "HEAD^").stdout.strip() == course_tip
        assert f"https://github.com/{s.course}/compare/{default}...stud:{s.branch}" in result.stdout
        assert f"https://github.com/{s.fork_name}/tree/{s.branch}" in result.stdout
        s.assert_confined(s.fork_name)

    @pytest.mark.parametrize("failure", ["creation", "missing", "ambiguous", "permission"])
    def test_failed_destination_resolution_refuses_without_push(self, tmp_path, failure):
        s = Sandbox(tmp_path, permission="READ")
        if failure == "creation":
            s.state["fork_failure"] = True
        elif failure == "missing":
            s.state["forks"] = [{"owner": {"login": "someone-else"}, "full_name": "someone-else/cursus"}]
        elif failure == "ambiguous":
            s.state["forks"].append({"owner": {"login": "stud"}, "full_name": "stud/another-fork"})
        else:
            s.state["view_failure"] = True
        before = s.refs()
        s.edit()
        s.run("01", success=False)
        assert s.refs() == before
        s.assert_no_push()


class TestConfinement:
    def test_outside_staged_unstaged_and_check_staged_changes_survive_even_empty_rerun(self, tmp_path):
        s = Sandbox(tmp_path)
        write(s.repo / "README.md", "private unfinished notes\n")
        write(s.repo / "outside.txt", "already staged\n")
        s.git("add", "outside.txt")
        write(s.repo / "sessions/08-other/exercises/other.txt", "not session 01\n")
        s.edit("turn-in-check.sh", '''#!/usr/bin/env bash
set -eu
printf 'check side effect\n' > ../../from-check.txt
git add -- ../../from-check.txt
''')
        s.edit()
        for _ in range(2):
            s.run("01")
            s.assert_confined()
            staged = s.git("diff", "--cached", "--name-only").stdout.splitlines()
            assert set(staged) == {"outside.txt", "from-check.txt"}
            assert (s.repo / "README.md").read_text() == "private unfinished notes\n"
            assert (s.repo / "outside.txt").read_text() == "already staged\n"
            assert (s.repo / "from-check.txt").read_text() == "check side effect\n"
            assert (s.repo / "sessions/08-other/exercises/other.txt").read_text() == "not session 01\n"
            assert s.git("show", "HEAD:README.md").stdout == "course baseline\n"
            assert s.git("show", "HEAD:outside.txt").stdout == "outside baseline\n"

    @pytest.mark.parametrize("args", [[], ["1"], ["../x"], ["99"]])
    def test_invalid_session_arguments(self, tmp_path, args):
        s = Sandbox(tmp_path)
        before = s.refs()
        s.edit()
        s.run(*args, success=False)
        assert s.refs() == before
        s.assert_no_push()

    @pytest.mark.parametrize("login", ["main:x", "../main", "", "stud\nother"])
    def test_invalid_github_handle(self, tmp_path, login):
        s = Sandbox(tmp_path)
        s.state["login"] = login
        before = s.refs()
        s.edit()
        s.run("01", success=False)
        assert s.refs() == before
        s.assert_no_push()

    def test_ambiguous_session_directories_refused(self, tmp_path):
        s = Sandbox(tmp_path)
        write(s.repo / "sessions/01-duplicate/exercises/answer.txt", "ambiguous\n")
        before = s.refs()
        s.run("01", success=False)
        assert s.refs() == before
        s.assert_no_push()

    def test_unrelated_feature_commits_are_not_carried(self, tmp_path):
        s = Sandbox(tmp_path)
        s.git("switch", "-c", "feat/unrelated")
        write(s.repo / "README.md", "unrelated committed work\n")
        s.git("add", "README.md")
        s.git("commit", "-m", "Unrelated feature")
        head, before = s.git("rev-parse", "HEAD").stdout, s.refs()
        s.edit()
        s.run("01", success=False)
        assert s.refs() == before
        assert s.git("rev-parse", "HEAD").stdout == head
        assert (s.repo / "README.md").read_text() == "unrelated committed work\n"
        s.assert_no_push()

    def test_existing_branch_with_outside_content_refuses(self, tmp_path):
        s = Sandbox(tmp_path)
        s.advance_remote(outside=True)
        before = s.refs()
        s.run("01", success=False)
        assert s.refs() == before
        s.assert_no_push()

    def test_divergent_history_refuses_without_rewriting(self, tmp_path):
        s = Sandbox(tmp_path)
        s.edit()
        s.run("01")
        s.advance_remote()
        s.edit("local-only.txt", "local commit\n")
        s.git("add", s.exercises)
        s.git("commit", "-m", "Local submission")
        head, before = s.git("rev-parse", "HEAD").stdout, s.refs()
        s.run("01", success=False)
        assert s.refs() == before
        assert s.git("rev-parse", "HEAD").stdout == head
        assert s.git("status", "--porcelain").stdout == ""
        s.assert_no_push()

    def test_switch_collision_preserves_uncommitted_work(self, tmp_path):
        s = Sandbox(tmp_path)
        s.advance_remote()
        s.edit("remote.txt", "local untracked file collides\n")
        before = s.refs()
        s.run("01", success=False)
        assert s.refs() == before
        assert (s.repo / s.exercises / "remote.txt").read_text() == "local untracked file collides\n"
        assert s.git("rev-parse", "HEAD").stdout.strip() == s.base
        s.assert_no_push()
