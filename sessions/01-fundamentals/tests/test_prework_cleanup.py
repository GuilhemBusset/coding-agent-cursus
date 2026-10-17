"""Issue 24: ownership-safe cleanup through both public setup entry points.

Reuse the locked offline Sandbox and report contracts. Git objects, transport,
hooks and lease rejection are real; all remotes are disposable local bare repos.
No checker functions are imported or patched. Races are synchronized at the
transport boundary, without sleeps. These are fixture runs, not A3 evidence.

The second non-fast-forward push can be rejected before pre-receive runs, so a
transport observer records both proposed OIDs; the receive hook independently
records what reached the server. We never require a refused delete to reach it.
"""

import json
import re
import sys

import pytest

from prework_live_agents import report
from test_prework import box, check, entrypoint, status


FIXED_DATE = "2026-01-02T03:04:05+00:00"


def setup_ref(box):
    return "refs/heads/setup-check/" + box.config["handle"]


def remote_refs(box, remote):
    return dict(line.split() for line in box.git_run(
        "--git-dir=" + str(remote), "for-each-ref",
        "--format=%(refname) %(objectname)").splitlines())


def tip(box):
    return remote_refs(box, box.course).get(setup_ref(box))


@pytest.fixture(autouse=True)
def protect_student_refs(box):
    """Every scenario protects main, homework and the dirty student checkout."""
    # Use another valid login, so the new cases cannot pass by fixing student-47.
    box.config["handle"] = "Learner-208"
    for remote in (box.course, box.fork):
        main = remote_refs(box, remote)["refs/heads/main"]
        for handle in (box.config["handle"], "another-student"):
            box.git_run("--git-dir=" + str(remote), "update-ref",
                        "refs/heads/homework/s01/" + handle, main)
    initial = {remote: remote_refs(box, remote) for remote in (box.course, box.fork)}
    student = box.snapshot()
    yield
    assert box.snapshot() == student, "Changed the student's files, index, HEAD or refs"
    for remote, refs in initial.items():
        current = remote_refs(box, remote)
        assert {name: oid for name, oid in current.items() if name != setup_ref(box)} == refs
    assert all(event["ref"] == setup_ref(box) for event in box.pushes()), (
        "Attempted to write a ref outside this student's setup-check branch")


def executable(path, source):
    path.write_text(f"#!{sys.executable}\n" + source, encoding="utf-8")
    path.chmod(0o755)


def move_after_receive(box):
    """Move the accepted probe to main before the client's first verification."""
    marker = box.root / "post-receive-move"
    executable(box.course / "hooks/post-receive", f'''
import pathlib, subprocess, sys
for line in sys.stdin:
    old, new, ref = line.split()
    if ref == {setup_ref(box)!r} and set(new) != {{"0"}}:
        main = subprocess.check_output([{box.git!r}, "rev-parse", "refs/heads/main"], text=True).strip()
        subprocess.run([{box.git!r}, "update-ref", ref, main, new], check=True)
        pathlib.Path({str(marker)!r}).write_text(main)
''')
    return marker


def observe_transport(box, *, move_before_delete=False, unreadable_after_delete=False):
    """Extend the CLI fixture, forwarding every command to its original handler.

    Observe proposed refspecs before Git can reject them client-side. For the
    race, change the branch immediately before real Git executes the deletion.
    The implementation must let Git enforce the expected old OID atomically.
    """
    proposals = box.root / "proposed-oids.jsonl"
    marker = box.root / "delete-boundary"
    shim = box.bin / "git"
    original = shim.read_text().split("\n", 1)[1]
    prefix = f'''
import json, pathlib, subprocess, sys
args = sys.argv[1:]
ref = {setup_ref(box)!r}
marker = pathlib.Path({str(marker)!r})
if "push" in args:
    deleting = "--delete" in args or "-d" in args or any(
        arg == ":" + ref or arg == ":" + ref.removeprefix("refs/heads/") for arg in args)
    if deleting:
        if {move_before_delete!r} and not marker.exists():
            main = subprocess.check_output(
                [{box.git!r}, "--git-dir=" + {str(box.course)!r}, "rev-parse", "refs/heads/main"],
                text=True).strip()
            subprocess.run([{box.git!r}, "--git-dir=" + {str(box.course)!r},
                            "update-ref", ref, main], check=True)
        marker.write_text("deletion boundary reached")
    else:
        for arg in args:
            source, sep, target = arg.partition(":")
            if sep and target in (ref, ref.removeprefix("refs/heads/")) and source:
                oid = subprocess.check_output(
                    [{box.git!r}, "rev-parse", source.lstrip("+")], text=True).strip()
                with open({str(proposals)!r}, "a") as stream:
                    stream.write(json.dumps(oid) + "\\n")
if {unreadable_after_delete!r} and "ls-remote" in args and marker.exists():
    print("PRIVATE_GIT_STDERR", file=sys.stderr)
    sys.exit(17)
'''
    executable(shim, prefix + original)
    return proposals, marker


def ownership_note(before, box):
    branch = setup_ref(box).removeprefix("refs/heads/")
    notes = [line for line in before.splitlines() if line.startswith("note:") and branch in line]
    assert notes, "A changed branch needs a note identifying the branch left alone"
    joined = " ".join(notes).lower()
    assert re.search(r"left (?:it )?alone|untouched|preserv|not (?:deleted|removed)", joined), joined
    assert "commit" in joined and re.search(r"different|another|not push|didn't push|not ours|not own", joined), joined
    assert "-X DELETE" not in before
    assert not re.search(r"gh\s+api|git\s+push.*(?:--delete|:refs/heads/)", joined), joined


def test_push_moved_before_verification_is_preserved(box, entrypoint):
    main = remote_refs(box, box.course)["refs/heads/main"]
    marker = move_after_receive(box)
    before, _, _ = check(box, entrypoint, False)
    assert marker.read_text() == main, "Fixture did not replace the accepted probe"
    assert tip(box) == main, "Cleanup deleted a branch that already belonged to someone else"
    status(before, "push", "FAIL")
    ownership_note(before, box)


def test_push_moved_between_verification_and_delete_is_preserved(box, entrypoint):
    main = remote_refs(box, box.course)["refs/heads/main"]
    _, marker = observe_transport(box, move_before_delete=True)
    before, _, _ = check(box, entrypoint, True)
    assert marker.exists(), "Fixture did not reach the deletion race"
    assert tip(box) == main, "Delete must reject a tip changed after verification"
    status(before, "push", "PASS")  # Verification succeeded; cleanup is only a note.
    ownership_note(before, box)


def test_push_same_second_probes_cannot_claim_each_others_ref(box, entrypoint):
    box.env.update(GIT_AUTHOR_DATE=FIXED_DATE, GIT_COMMITTER_DATE=FIXED_DATE)
    box.hook(box.course, reject="delete")
    proposals, _ = observe_transport(box)
    first, _, _ = check(box, entrypoint, True)
    first_oid = tip(box)
    assert first_oid
    status(first, "push", "PASS")
    # Run the second check before asserting its report: inspect both proposals
    # even on the old implementation, whose identical OID falsely passes.
    result = box.run(entrypoint)
    oids = [json.loads(line) for line in proposals.read_text().splitlines()]
    assert len(oids) == 2, "Expected one probe proposal from each run"
    assert oids[0] == first_oid and oids[0] != oids[1], (
        "Same-second runs must generate distinct probe commits")
    assert tip(box) == first_oid, "Second run replaced or deleted the first run's ref"
    received = [event for event in box.pushes() if set(event["new"]) != {"0"}]
    assert received and received[0]["new"] == first_oid
    assert all(not event["tree"] for event in received), "Probe must contain no student files"
    before, _ = report(result, False)
    status(before, "push", "FAIL")


def test_push_preexisting_legacy_empty_tree_commit_survives(box, entrypoint):
    # Reconstruct the historical probe from its public object contents. No
    # current implementation identity/message is required to match this fixture.
    box.env.update(GIT_AUTHOR_DATE=FIXED_DATE, GIT_COMMITTER_DATE=FIXED_DATE)
    identity = {key: box.env[key] for key in (
        "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")}
    box.env.update(GIT_AUTHOR_NAME="Cursus setup check", GIT_COMMITTER_NAME="Cursus setup check",
                   GIT_AUTHOR_EMAIL="setup-check@example.invalid",
                   GIT_COMMITTER_EMAIL="setup-check@example.invalid")
    tree = box.git_run("--git-dir=" + str(box.course), "mktree", input="")
    original = box.git_run("--git-dir=" + str(box.course), "commit-tree", tree,
                           input="Cursus setup check: safe to delete\n")
    box.env.update(identity)
    box.git_run("--git-dir=" + str(box.course), "update-ref", setup_ref(box), original)
    contents = box.git_run("--git-dir=" + str(box.course), "cat-file", "commit", original)
    result = box.run(entrypoint)
    assert tip(box) == original, "Pre-existing empty-tree branch was overwritten or deleted"
    assert box.git_run("--git-dir=" + str(box.course), "cat-file", "commit", original) == contents
    before, _ = report(result, False)
    status(before, "push", "FAIL")


def test_push_cleanup_unreadable_tip_requires_conditional_advice(box, entrypoint):
    box.hook(box.course, reject="delete")
    observe_transport(box, unreadable_after_delete=True)
    before, _, _ = check(box, entrypoint, True)
    oid = tip(box)
    assert oid, "Fixture should retain the probe after rejected cleanup"
    status(before, "push", "PASS")
    notes = " ".join(line for line in before.splitlines() if line.startswith("note:"))
    assert setup_ref(box).removeprefix("refs/heads/") in notes
    assert box.config["origin_slug"] in notes
    assert oid[:12] in notes, "Unreadable cleanup must identify the expected probe OID"
    assert re.search(r"only if|only when", notes, re.I), notes
    assert "-X DELETE" not in notes, "Unreadable ref must not get blind deletion advice"


def test_push_unreadable_verification_still_cleans_own_probe(box, entrypoint):
    box.config["ls_remote_fail"] = True
    before, _, _ = check(box, entrypoint, False)
    status(before, "push", "FAIL")
    assert tip(box) is None, "Unreadable verification must still attempt ownership-safe cleanup"
    created = [event["new"] for event in box.pushes() if set(event["new"]) != {"0"}]
    assert len(created) == 1
    notes = " ".join(line for line in before.splitlines() if line.startswith("note:"))
    assert created[0][:12] in notes
    assert re.search(r"only if|only when", notes, re.I), notes
    assert "-X DELETE" not in notes
