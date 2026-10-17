"""`GhCli` against a fake `gh`: which failures are retried, how often, and what is raised."""

import json
import subprocess
import unittest

import helpers  # noqa: F401 - puts the package on the path

from implement_loop.github import GhCli, GitHubError, GitHubUnavailable, transient

BAD_GATEWAY = "gh: HTTP 502"
SERVER_ERROR = "gh: Server Error (HTTP 500)"
NOT_FOUND = "gh: Not Found (HTTP 404)"
UNPROCESSABLE = "gh: Validation Failed (HTTP 422)"
FORBIDDEN = "gh: Resource not accessible by integration (HTTP 403)"
SECONDARY = ("gh: You have exceeded a secondary rate limit. Please wait a few minutes before you try again. "
             "(HTTP 403)")
TOO_MANY = "gh: Too Many Requests (HTTP 429)"
ABUSE = "gh: You have triggered an abuse detection mechanism. (HTTP 403)"
NO_HOST = "error connecting to api.github.com\ncheck your internet connection or https://githubstatus.com"
REFUSED = 'Post "https://api.github.com/repos/o/r/issues": dial tcp 140.82.112.6:443: connect: connection refused'
RESET = 'Get "https://api.github.com/repos/o/r/issues/1": read tcp 10.0.0.2:5000->140.82.112.6:443: read: connection reset by peer'
TIMEOUT = 'Get "https://api.github.com/repos/o/r/issues/1": net/http: request canceled (Client.Timeout exceeded)'
EOF = 'Post "https://api.github.com/repos/o/r/pulls": unexpected EOF'
TLS = 'Get "https://api.github.com/repos/o/r/issues/1": net/http: TLS handshake timeout'


def ok(payload) -> tuple[int, str, str]:
    return 0, json.dumps(payload), ""


def fail(stderr: str, stdout: str = "") -> tuple[int, str, str]:
    return 1, stdout, stderr


class FakeGh:
    """Plays `gh api`: answers each call with the next scripted (code, stdout, stderr)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, args, input=None, capture_output=True, text=True):
        self.calls.append((args, input))
        code, out, err = self.answers.pop(0)
        return subprocess.CompletedProcess(args, code, out, err)

    def methods(self) -> list[str]:
        return [args[args.index("--method") + 1] for args, _ in self.calls]


class GhCliRetryTests(unittest.TestCase):
    def client(self, *answers) -> tuple[GhCli, FakeGh, list[float]]:
        fake, slept = FakeGh(*answers), []
        return GhCli("o/r", runner=fake, sleep=slept.append), fake, slept

    def test_the_default_backoff_is_5_15_45_seconds(self):
        gh, fake, slept = self.client(*[fail(BAD_GATEWAY)] * 4)
        with self.assertRaises(GitHubUnavailable) as raised:
            gh.get_issue(1)
        self.assertEqual(slept, [5, 15, 45])
        self.assertEqual(len(fake.calls), 4)
        self.assertIn("4 attempts", str(raised.exception))
        self.assertIn("HTTP 502", str(raised.exception))

    def test_an_outage_is_a_github_error_too(self):
        gh, _, _ = self.client(*[fail(BAD_GATEWAY)] * 4)
        with self.assertRaises(GitHubError):   # existing handlers keep catching it
            gh.get_issue(1)

    def test_a_transient_read_failure_recovers(self):
        for stderr in (BAD_GATEWAY, SERVER_ERROR, TOO_MANY, SECONDARY, ABUSE, NO_HOST, REFUSED, RESET, TIMEOUT, EOF, TLS):
            with self.subTest(stderr=stderr):
                gh, fake, slept = self.client(fail(stderr), fail(stderr), ok({"number": 1}))
                self.assertEqual(gh.get_issue(1), {"number": 1})
                self.assertEqual((len(fake.calls), slept), (3, [5, 15]))

    def test_a_4xx_answer_fails_at_once(self):
        for stderr in (NOT_FOUND, UNPROCESSABLE, FORBIDDEN, "gh: Bad credentials (HTTP 401)",
                       "To get started with GitHub CLI, please run:  gh auth login"):
            with self.subTest(stderr=stderr):
                gh, fake, slept = self.client(fail(stderr))
                with self.assertRaises(GitHubError) as raised:
                    gh.get_issue(1)
                self.assertNotIsInstance(raised.exception, GitHubUnavailable)
                self.assertEqual((len(fake.calls), slept), (1, []))
                self.assertIn("gh api GET repos/o/r/issues/1 failed", str(raised.exception))

    def test_ok_codes_still_mean_nothing_to_do(self):
        gh, fake, _ = self.client(fail(NOT_FOUND))
        self.assertIsNone(gh.remove_label(1, "loop:design"))
        self.assertEqual(len(fake.calls), 1)

    def test_an_ok_code_after_a_retry_still_counts(self):
        gh, fake, slept = self.client(fail(BAD_GATEWAY), fail(NOT_FOUND))
        self.assertIsNone(gh.remove_label(1, "loop:design"))
        self.assertEqual((fake.methods(), slept), (["DELETE", "DELETE"], [5]))

    def test_idempotent_writes_are_retried_on_any_transient_failure(self):
        cases = (
            ("merge", lambda gh: gh.merge_pr(7, "abc123"), "PUT", ok({"merged": True})),
            ("update_pr", lambda gh: gh.update_pr(7, "body"), "PATCH", ok({"number": 7})),
            ("update_comment", lambda gh: gh.update_comment(9, "body"), "PATCH", ok({"id": 9})),
            ("edit_issue", lambda gh: gh.edit_issue(1, state="closed"), "PATCH", ok({"number": 1})),
            ("remove_label", lambda gh: gh.remove_label(1, "x"), "DELETE", (0, "", "")),
            ("add_labels", lambda gh: gh.add_labels(1, ["x"]), "POST", ok([{"name": "x"}])),
            ("ensure_label", lambda gh: gh.ensure_label("x", "ededed", "d"), "POST", ok({"name": "x"})),
        )
        for name, call, method, last in cases:
            with self.subTest(name):
                gh, fake, slept = self.client(fail(BAD_GATEWAY), fail(RESET), last)
                call(gh)
                self.assertEqual(fake.methods(), [method] * 3)
                self.assertEqual(slept, [5, 15])

    def test_the_merge_is_retried_with_the_same_head_bound_body(self):
        gh, fake, _ = self.client(fail(TIMEOUT), ok({"merged": True}))
        gh.merge_pr(7, "abc123")
        bodies = [json.loads(body) for _, body in fake.calls]
        self.assertEqual(bodies, [{"sha": "abc123", "merge_method": "squash"}] * 2)

    def test_a_label_created_before_a_lost_answer_is_fine(self):
        gh, fake, _ = self.client(fail(BAD_GATEWAY), fail(UNPROCESSABLE))
        self.assertIsNone(gh.ensure_label("x", "ededed", "d"))
        self.assertEqual(len(fake.calls), 2)

    def test_a_creating_post_is_retried_when_github_never_saw_it(self):
        creations = (
            ("create_pr", lambda gh: gh.create_pr("feat/x", "main", "t", "b")),
            ("create_issue", lambda gh: gh.create_issue("t", "b", ["l"])),
            ("create_comment", lambda gh: gh.create_comment(1, "b")),
        )
        for name, call in creations:
            for stderr in (NO_HOST, REFUSED, TLS, TOO_MANY, SECONDARY):
                with self.subTest(name, stderr=stderr):
                    gh, fake, slept = self.client(fail(stderr), ok({"number": 3}))
                    self.assertEqual(call(gh), {"number": 3})
                    self.assertEqual((fake.methods(), slept), (["POST", "POST"], [5]))

    def test_a_creating_post_that_may_have_taken_effect_is_not_repeated(self):
        creations = (
            ("create_pr", lambda gh: gh.create_pr("feat/x", "main", "t", "b")),
            ("create_issue", lambda gh: gh.create_issue("t", "b", ["l"])),
            ("create_comment", lambda gh: gh.create_comment(1, "b")),
        )
        for name, call in creations:
            for stderr in (BAD_GATEWAY, SERVER_ERROR, RESET, TIMEOUT, EOF):
                with self.subTest(name, stderr=stderr):
                    gh, fake, slept = self.client(fail(stderr))
                    with self.assertRaises(GitHubUnavailable) as raised:
                        call(gh)
                    self.assertEqual((len(fake.calls), slept), (1, []))
                    self.assertIn("may have taken effect", str(raised.exception))

    def test_a_rerun_that_may_have_started_is_not_repeated(self):
        runs = ok({"workflow_runs": [{"id": 5, "conclusion": "failure"}]})
        gh, fake, slept = self.client(fail(BAD_GATEWAY), runs, fail(BAD_GATEWAY))
        with self.assertRaises(GitHubUnavailable):
            gh.rerun_failed("abc123")
        self.assertEqual(fake.methods(), ["GET", "GET", "POST"], "the listing is retried, the re-run is not")
        self.assertEqual(slept, [5])

    def test_a_creating_post_still_refused_after_the_retries_is_an_outage(self):
        gh, fake, slept = self.client(*[fail(REFUSED)] * 4)
        with self.assertRaises(GitHubUnavailable):
            gh.create_pr("feat/x", "main", "t", "b")
        self.assertEqual((len(fake.calls), slept), (4, [5, 15, 45]))

    def test_a_4xx_on_a_post_fails_at_once(self):
        gh, fake, _ = self.client(fail(UNPROCESSABLE))
        with self.assertRaises(GitHubError) as raised:
            gh.create_pr("feat/x", "main", "t", "b")
        self.assertNotIsInstance(raised.exception, GitHubUnavailable)
        self.assertEqual(len(fake.calls), 1)

    def test_paged_reads_retry_each_page(self):
        page1 = [{"id": i} for i in range(100)]
        gh, fake, slept = self.client(ok(page1), fail(BAD_GATEWAY), ok([{"id": 100}]))
        self.assertEqual(len(gh.list_comments(1)), 101)
        self.assertEqual(slept, [5])
        self.assertTrue(fake.calls[1][0][-1].endswith("page=2") and fake.calls[2][0][-1].endswith("page=2"))

    def test_the_delays_are_configurable(self):
        fake, slept = FakeGh(fail(BAD_GATEWAY), fail(BAD_GATEWAY)), []
        gh = GhCli("o/r", runner=fake, sleep=slept.append, retry_delays=(1,))
        with self.assertRaises(GitHubUnavailable):
            gh.get_issue(1)
        self.assertEqual((len(fake.calls), slept), (2, [1]))


class TransientTests(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(transient(BAD_GATEWAY), "unknown")
        self.assertEqual(transient("gh: Service Unavailable (HTTP 503)"), "unknown")
        self.assertEqual(transient(TOO_MANY), "not-sent")
        self.assertEqual(transient(SECONDARY), "not-sent")
        self.assertEqual(transient(ABUSE), "not-sent")
        self.assertEqual(transient("gh: API rate limit exceeded for user ID 1. (HTTP 403)"), "not-sent")
        self.assertEqual(transient(NO_HOST), "not-sent")
        self.assertEqual(transient("dial tcp: lookup api.github.com: no such host"), "not-sent")
        self.assertEqual(transient("curl: (6) Could not resolve host: api.github.com"), "not-sent")
        self.assertEqual(transient(REFUSED), "not-sent")
        self.assertEqual(transient(TLS), "not-sent")
        self.assertEqual(transient(RESET), "unknown")
        self.assertEqual(transient(TIMEOUT), "unknown")
        self.assertEqual(transient("context deadline exceeded: i/o timeout"), "unknown")
        self.assertEqual(transient(EOF), "unknown")
        self.assertIsNone(transient(NOT_FOUND))
        self.assertIsNone(transient(UNPROCESSABLE))
        self.assertIsNone(transient(FORBIDDEN))
        self.assertIsNone(transient("gh: Conflict (HTTP 409)", '{"message": "timeout of the EOF"}'),
                          "an HTTP answer is judged by its status, not by words in its body")
        self.assertIsNone(transient(""))


if __name__ == "__main__":
    unittest.main()
