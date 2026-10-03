"""GitHub access. `GhCli` talks to the real API through `gh api`; `FakeGitHub` is the
in-memory double used by the tests; `RecordingGitHub` captures real read responses as a
fixture for those tests."""

from __future__ import annotations

import json
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Protocol

PER_PAGE = 100


class GitHubError(RuntimeError):
    pass


class GitHub(Protocol):
    # reads
    def get_issue(self, n: int) -> dict: ...
    def list_sub_issues(self, n: int) -> list[dict]: ...
    def list_blocked_by(self, n: int) -> list[dict]: ...
    def list_comments(self, n: int) -> list[dict]: ...
    def find_pr(self, head: str) -> dict | None: ...
    def required_check(self, sha: str, name: str) -> str | None: ...
    # writes
    def create_comment(self, n: int, body: str) -> dict: ...
    def update_comment(self, comment_id: int, body: str) -> dict: ...
    def edit_issue(self, n: int, *, body: str | None = None, state: str | None = None, state_reason: str | None = None) -> dict: ...
    def add_labels(self, n: int, labels: list[str]) -> None: ...
    def remove_label(self, n: int, label: str) -> None: ...
    def ensure_label(self, name: str, color: str, description: str) -> None: ...
    def create_pr(self, head: str, base: str, title: str, body: str) -> dict: ...
    def update_pr(self, n: int, body: str) -> dict: ...
    def merge_pr(self, n: int, sha: str, method: str = "squash") -> dict: ...


class GhCli:
    """The real API, through the authenticated `gh` CLI. Pins the REST API version."""

    def __init__(self, repo: str, api_version: str = "2022-11-28", runner: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        self.repo = repo
        self.api_version = api_version
        self._run = runner

    def _api(self, path: str, method: str = "GET", payload: dict | None = None, ok_codes: tuple[int, ...] = ()) -> Any:
        args = ["gh", "api", "--method", method, "-H", f"X-GitHub-Api-Version: {self.api_version}",
                "-H", "Accept: application/vnd.github+json", path]
        if payload is not None:
            args += ["--input", "-"]
        proc = self._run(args, input=json.dumps(payload) if payload is not None else None,
                         capture_output=True, text=True)
        if proc.returncode != 0:
            for code in ok_codes:
                if f"HTTP {code}" in (proc.stderr or ""):
                    return None
            raise GitHubError(f"gh api {method} {path} failed: {(proc.stderr or proc.stdout).strip()[:500]}")
        out = proc.stdout.strip()
        return json.loads(out) if out else None

    def _pages(self, path: str) -> list[dict]:
        items: list[dict] = []
        sep = "&" if "?" in path else "?"
        page = 1
        while True:
            batch = self._api(f"{path}{sep}per_page={PER_PAGE}&page={page}") or []
            items.extend(batch)
            if len(batch) < PER_PAGE:
                return items
            page += 1

    def _r(self, tail: str) -> str:
        return f"repos/{self.repo}/{tail}"

    def get_issue(self, n):
        return self._api(self._r(f"issues/{n}"))

    def list_sub_issues(self, n):
        return self._pages(self._r(f"issues/{n}/sub_issues"))

    def list_blocked_by(self, n):
        return self._pages(self._r(f"issues/{n}/dependencies/blocked_by"))

    def list_comments(self, n):
        return self._pages(self._r(f"issues/{n}/comments"))

    def find_pr(self, head):
        owner = self.repo.split("/")[0]
        prs = self._api(self._r(f"pulls?state=all&head={urllib.parse.quote(owner + ':' + head)}")) or []
        open_prs = [p for p in prs if p.get("state") == "open"]
        return (open_prs or prs or [None])[0]

    def required_check(self, sha, name):
        data = self._api(self._r(f"commits/{sha}/check-runs?check_name={urllib.parse.quote(name)}&filter=latest")) or {}
        runs = data.get("check_runs", [])
        if not runs:
            return None
        run = runs[0]
        return run.get("conclusion") if run.get("status") == "completed" else "pending"

    def create_comment(self, n, body):
        return self._api(self._r(f"issues/{n}/comments"), "POST", {"body": body})

    def update_comment(self, comment_id, body):
        return self._api(self._r(f"issues/comments/{comment_id}"), "PATCH", {"body": body})

    def edit_issue(self, n, *, body=None, state=None, state_reason=None):
        payload = {k: v for k, v in {"body": body, "state": state, "state_reason": state_reason}.items() if v is not None}
        return self._api(self._r(f"issues/{n}"), "PATCH", payload)

    def add_labels(self, n, labels):
        if labels:
            self._api(self._r(f"issues/{n}/labels"), "POST", {"labels": labels})

    def remove_label(self, n, label):
        self._api(self._r(f"issues/{n}/labels/{urllib.parse.quote(label, safe='')}"), "DELETE", ok_codes=(404,))

    def ensure_label(self, name, color, description):
        self._api(self._r("labels"), "POST", {"name": name, "color": color, "description": description}, ok_codes=(422,))

    def create_pr(self, head, base, title, body):
        return self._api(self._r("pulls"), "POST", {"head": head, "base": base, "title": title, "body": body})

    def update_pr(self, n, body):
        return self._api(self._r(f"pulls/{n}"), "PATCH", {"body": body})

    def merge_pr(self, n, sha, method="squash"):
        # `sha` makes GitHub refuse the merge unless the PR head is exactly the reviewed commit.
        return self._api(self._r(f"pulls/{n}/merge"), "PUT", {"sha": sha, "merge_method": method})


class RecordingGitHub:
    """Wraps a real client and records read responses, to build offline test fixtures."""

    READS = ("get_issue", "list_sub_issues", "list_blocked_by")

    def __init__(self, inner: GitHub):
        self.inner = inner
        self.fixture: dict[str, dict] = {name: {} for name in self.READS}

    def __getattr__(self, name):
        attr = getattr(self.inner, name)
        if name not in self.READS:
            return attr

        def recorded(n):
            result = attr(n)
            self.fixture[name][str(n)] = result
            return result
        return recorded

    def save(self, path: Path) -> None:
        """Each issue once under "issues"; listings keep only issue numbers."""
        issues: dict[str, dict] = {}
        for key, value in self.fixture["get_issue"].items():
            issues[key] = slim(value)
        listings: dict[str, dict[str, list[int]]] = {"sub_issues": {}, "blocked_by": {}}
        for name, target in (("list_sub_issues", "sub_issues"), ("list_blocked_by", "blocked_by")):
            for key, items in self.fixture[name].items():
                listings[target][key] = [i["number"] for i in items]
                for i in items:
                    issues.setdefault(str(i["number"]), slim(i))
        path.write_text(json.dumps({"issues": issues, **listings}, indent=1, sort_keys=True) + "\n")


_KEEP = ("number", "title", "state", "body", "labels", "id", "html_url", "sub_issues_summary", "issue_dependencies_summary")


def slim(issue: dict) -> dict:
    """Only the fields the engine reads, so fixtures stay small and readable."""
    out = {k: issue[k] for k in _KEEP if k in issue}
    out["labels"] = [{"name": l["name"]} if isinstance(l, dict) else {"name": l} for l in issue.get("labels", [])]
    return out


class FakeGitHub:
    """In-memory GitHub. Reads come from a fixture; writes are applied and logged.

    `on_merge(branch, sha)` lets a test perform the actual git merge in a local bare remote.
    """

    def __init__(self, fixture: dict | None = None, owner: str = "test", on_merge: Callable[[str, str], str] | None = None):
        fixture = fixture or {}
        self.issues: dict[int, dict] = {int(k): v for k, v in fixture.get("issues", {}).items()}
        self.subs: dict[int, list[int]] = {int(k): list(v) for k, v in fixture.get("sub_issues", {}).items()}
        self.blocked: dict[int, list[int]] = {int(k): list(v) for k, v in fixture.get("blocked_by", {}).items()}
        # a recorded issue knows its true counts even when its listing was never fetched
        for n, issue in self.issues.items():
            if n not in self.subs and (issue.get("sub_issues_summary") or {}).get("total"):
                raise ValueError(f"fixture lacks the sub-issue listing of #{n}")
        self.comments: dict[int, list[dict]] = {}
        self.labels: set[str] = set()
        self.prs: dict[int, dict] = {}
        self.checks: dict[str, str] = {}
        self.default_check: str | None = "success"
        self.calls: list[tuple] = []
        self.owner = owner
        self.on_merge = on_merge
        self._next_id = 1000

    # helpers for tests
    def add_issue(self, n: int, title: str, body: str = "", labels: tuple[str, ...] = (), state: str = "open",
                  subs: tuple[int, ...] = (), blocked_by: tuple[int, ...] = ()) -> None:
        self.issues[n] = {"number": n, "title": title, "state": state, "body": body, "id": 10_000 + n,
                          "labels": [{"name": l} for l in labels], "html_url": f"https://github.test/issues/{n}"}
        self.subs[n] = list(subs)
        self.blocked[n] = list(blocked_by)

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _issue(self, n):
        if n not in self.issues:
            raise GitHubError(f"issue {n} not found")
        data = dict(self.issues[n])
        data["sub_issues_summary"] = {"total": len(self.subs.get(n, []))}
        data["issue_dependencies_summary"] = {"total_blocked_by": len(self.blocked.get(n, []))}
        return data

    # reads
    def get_issue(self, n):
        return self._issue(n)

    def list_sub_issues(self, n):
        return [self._issue(c) for c in self.subs.get(n, [])]

    def list_blocked_by(self, n):
        return [self._issue(c) for c in self.blocked.get(n, [])]

    def list_comments(self, n):
        return list(self.comments.get(n, []))

    def find_pr(self, head):
        matches = [p for p in self.prs.values() if p["head"]["ref"] == head]
        open_prs = [p for p in matches if p["state"] == "open"]
        return (open_prs or matches or [None])[0]

    def required_check(self, sha, name):
        return self.checks.get(sha, self.default_check)

    # writes
    def create_comment(self, n, body):
        c = {"id": self._id(), "body": body, "html_url": f"https://github.test/issues/{n}#issuecomment-{self._next_id}"}
        self.comments.setdefault(n, []).append(c)
        self.calls.append(("create_comment", n))
        return c

    def update_comment(self, comment_id, body):
        for cs in self.comments.values():
            for c in cs:
                if c["id"] == comment_id:
                    c["body"] = body
                    self.calls.append(("update_comment", comment_id))
                    return c
        raise GitHubError(f"comment {comment_id} not found")

    def edit_issue(self, n, *, body=None, state=None, state_reason=None):
        target = self.issues[n] if n in self.issues else self.prs[n]
        if body is not None:
            target["body"] = body
        if state is not None:
            target["state"] = state
        self.calls.append(("edit_issue", n, state))
        return target

    def add_labels(self, n, labels):
        target = self.issues.get(n) or self.prs[n]
        names = {l["name"] for l in target.setdefault("labels", [])}
        for l in labels:
            if l not in names:
                target["labels"].append({"name": l})
        self.calls.append(("add_labels", n, tuple(labels)))

    def remove_label(self, n, label):
        target = self.issues.get(n) or self.prs[n]
        target["labels"] = [l for l in target.get("labels", []) if l["name"] != label]

    def ensure_label(self, name, color, description):
        self.labels.add(name)

    def create_pr(self, head, base, title, body):
        n = 5000 + len(self.prs) + 1
        pr = {"number": n, "head": {"ref": head}, "base": {"ref": base}, "title": title, "body": body,
              "state": "open", "merged": False, "html_url": f"https://github.test/pull/{n}", "labels": []}
        self.prs[n] = pr
        self.calls.append(("create_pr", head))
        return pr

    def update_pr(self, n, body):
        self.prs[n]["body"] = body
        return self.prs[n]

    def merge_pr(self, n, sha, method="squash"):
        pr = self.prs[n]
        if pr.get("head_sha") and pr["head_sha"] != sha:
            raise GitHubError("Head branch was modified. Review and try the merge again.")
        merge_sha = self.on_merge(pr["head"]["ref"], sha) if self.on_merge else f"merged-{sha}"
        pr.update(state="closed", merged=True, merge_commit_sha=merge_sha)
        self.calls.append(("merge_pr", n, sha))
        return {"merged": True, "sha": merge_sha}
