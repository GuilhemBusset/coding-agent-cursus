#!/usr/bin/env bash
# Hermetic test for scripts/ship.sh: runs it against a throwaway bare remote,
# with this repo's real git hooks active, and checks that repeated publication
# never needs --force. No network, no GitHub. Run from anywhere:
#
#   bash scripts/test-ship.sh
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ship="${SHIP_SCRIPT:-$repo_root/scripts/ship.sh}"  # override to test another version
hooks="$repo_root/.githooks"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

fail() { echo "[test-ship] FAIL: $*" >&2; exit 1; }
pass() { echo "[test-ship] ok: $*"; }

git_id() {
  git -C "$1" config user.name "Ship Test"
  git -C "$1" config user.email "ship-test@example.invalid"
  git -C "$1" config commit.gpgsign false
}

# A bare remote with one commit on main.
git init -q --bare -b main "$tmp/remote.git"
git clone -q "$tmp/remote.git" "$tmp/seed" 2>/dev/null
git_id "$tmp/seed"
echo base > "$tmp/seed/base.txt"
git -C "$tmp/seed" add base.txt
git -C "$tmp/seed" commit -q -m "base"
git -C "$tmp/seed" push -q origin HEAD:main

# The author's clone, with the repo's pre-commit and pre-push hooks active.
git clone -q "$tmp/remote.git" "$tmp/work"
git_id "$tmp/work"
git -C "$tmp/work" config core.hooksPath "$hooks"

# 1. First publication rebases onto main and pushes.
git -C "$tmp/work" switch -q -c feat/demo
echo one > "$tmp/work/one.txt"
git -C "$tmp/work" add one.txt
git -C "$tmp/work" commit -q -m "one"
echo main-2 > "$tmp/seed/main2.txt"
git -C "$tmp/seed" add main2.txt
git -C "$tmp/seed" commit -q -m "main moves before first push"
git -C "$tmp/seed" push -q origin HEAD:main
(cd "$tmp/work" && bash "$ship" >/dev/null 2>&1) || fail "first publication failed"
git -C "$tmp/work" merge-base --is-ancestor origin/main HEAD || fail "first publication did not include main"
[ "$(git -C "$tmp/work" rev-list --merges origin/main..HEAD | wc -l)" -eq 0 ] || fail "first publication should be linear (rebase)"
first_tip="$(git -C "$tmp/remote.git" rev-parse feat/demo)"
pass "first publication rebases onto main and pushes"

# 2. After main moves again, re-publishing merges main in and fast-forwards the remote branch.
echo main-3 > "$tmp/seed/main3.txt"
git -C "$tmp/seed" add main3.txt
git -C "$tmp/seed" commit -q -m "main moves after first push"
git -C "$tmp/seed" push -q origin HEAD:main
echo two > "$tmp/work/two.txt"
git -C "$tmp/work" add two.txt
git -C "$tmp/work" commit -q -m "two"
(cd "$tmp/work" && bash "$ship" >/dev/null 2>&1) || fail "re-publication failed (would it have needed --force?)"
second_tip="$(git -C "$tmp/remote.git" rev-parse feat/demo)"
git -C "$tmp/remote.git" merge-base --is-ancestor "$first_tip" "$second_tip" || fail "remote branch history was rewritten"
git -C "$tmp/remote.git" merge-base --is-ancestor main feat/demo || fail "re-publication did not include the new main"
pass "re-publication merges main and fast-forwards the remote branch"

# 3. Re-publishing with nothing new on main and nothing new locally still succeeds without a merge commit.
before="$(git -C "$tmp/work" rev-parse HEAD)"
echo three > "$tmp/work/three.txt"
git -C "$tmp/work" add three.txt
git -C "$tmp/work" commit -q -m "three"
(cd "$tmp/work" && bash "$ship" >/dev/null 2>&1) || fail "re-publication with main unchanged failed"
[ "$(git -C "$tmp/work" rev-list --merges "$before"..HEAD | wc -l)" -eq 0 ] || fail "unneeded merge commit created"
pass "re-publication with main unchanged adds no merge commit"

# 4. A local branch missing commits from its remote branch is refused, and nothing is pushed.
git clone -q "$tmp/remote.git" "$tmp/other"
git_id "$tmp/other"
git -C "$tmp/other" switch -q feat/demo
echo other > "$tmp/other/other.txt"
git -C "$tmp/other" add other.txt
git -C "$tmp/other" commit -q -m "pushed from elsewhere"
git -C "$tmp/other" push -q origin feat/demo
remote_tip="$(git -C "$tmp/remote.git" rev-parse feat/demo)"
echo four > "$tmp/work/four.txt"
git -C "$tmp/work" add four.txt
git -C "$tmp/work" commit -q -m "four"
if (cd "$tmp/work" && bash "$ship" >/dev/null 2>&1); then
  fail "a branch behind its remote should be refused"
fi
[ "$(git -C "$tmp/remote.git" rev-parse feat/demo)" = "$remote_tip" ] || fail "remote branch changed after a refused ship"
pass "a branch behind its remote is refused and nothing is pushed"

main_moves() {
  echo "$1" > "$tmp/seed/$1.txt"
  git -C "$tmp/seed" add "$1.txt"
  git -C "$tmp/seed" commit -q -m "main moves: $1"
  git -C "$tmp/seed" push -q origin HEAD:main
}

# 5. An unpublished branch that already contains main is pushed unchanged.
git -C "$tmp/work" fetch -q origin main
git -C "$tmp/work" switch -q -c feat/current origin/main
echo current > "$tmp/work/current.txt"
git -C "$tmp/work" add current.txt
git -C "$tmp/work" commit -q -m "current"
before="$(git -C "$tmp/work" rev-parse HEAD)"
(cd "$tmp/work" && bash "$ship" >/dev/null 2>&1) || fail "shipping a branch that contains main failed"
[ "$(git -C "$tmp/work" rev-parse HEAD)" = "$before" ] || fail "a branch that contains main was rewritten"
[ "$(git -C "$tmp/remote.git" rev-parse feat/current)" = "$before" ] || fail "a branch that contains main was not pushed as is"
pass "an unpublished branch that contains main is pushed unchanged"

# 6. An unpublished branch carrying a merge commit gets main merged in, keeping that merge.
git -C "$tmp/work" switch -q -c feat/merged origin/main
echo merged > "$tmp/work/merged.txt"
git -C "$tmp/work" add merged.txt
git -C "$tmp/work" commit -q -m "merged"
main_moves main-4
git -C "$tmp/work" fetch -q origin main
git -C "$tmp/work" merge -q --no-edit origin/main
merge_commit="$(git -C "$tmp/work" rev-parse HEAD)"
main_moves main-5
(cd "$tmp/work" && bash "$ship" >/dev/null 2>&1) || fail "shipping an unpublished branch with a merge commit failed"
pushed="$(git -C "$tmp/remote.git" rev-parse feat/merged)"
git -C "$tmp/remote.git" merge-base --is-ancestor "$merge_commit" "$pushed" || fail "the branch's merge commit was dropped (rebased?)"
git -C "$tmp/remote.git" merge-base --is-ancestor main "$pushed" || fail "the new main was not merged in"
pass "an unpublished branch with a merge commit gets main merged in and keeps its merge"

# 7. Shipping from main is refused by the script, and the pre-push hook still guards main.
git -C "$tmp/work" switch -q main
if (cd "$tmp/work" && bash "$ship" >/dev/null 2>&1); then
  fail "shipping from main should be refused"
fi
if git -C "$tmp/work" push -q origin HEAD:refs/heads/main 2>/dev/null; then
  fail "pre-push hook did not block a push to main"
fi
pass "main stays protected (script refusal and pre-push hook)"

echo "[test-ship] all checks passed"
