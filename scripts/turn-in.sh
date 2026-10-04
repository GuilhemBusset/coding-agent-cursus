#!/usr/bin/env bash
# Portable, agent-independent core of the turn-in skill (/turn-in in Claude Code,
# $turn-in in Codex). See docs/adr/0009-homework-on-per-student-branches.md.
#
#   scripts/turn-in.sh <NN>        (for example: scripts/turn-in.sh 01)
#
# Commits the student's work under sessions/<NN>-*/exercises/ to their own branch
# homework/s<NN>/<handle> and pushes it, with retry/backoff. Homework branches never
# merge to main. A new branch starts from the course repo's default branch; an
# existing one only ever fast-forwards, and every run adds exactly one commit, so the
# history keeps every submission. Only the session's exercises/ folder is staged and
# committed; anything else in the working tree or index is left untouched. If the
# session ships exercises/turn-in-check.sh, its exit code gates the commit and push.
#
# Students without push access to the course repo push to their fork instead (created
# with gh if needed); a clone of a fork pushes to that fork. Either way the script
# prints a compare URL against the course repo.
#
# Never force-pushes, never uses --no-verify, never pushes to main/master, never
# stashes, resets, rebases or resolves conflicts. Requires git and an authenticated gh.
set -euo pipefail

die() {
  echo "[turn-in] $*" >&2
  exit 1
}
note() { echo "[turn-in] $*" >&2; }

if [ "$#" -ne 1 ]; then
  die "Usage: scripts/turn-in.sh <NN>, the two-digit session number (for example: scripts/turn-in.sh 01)."
fi
nn=$1
if ! [[ $nn =~ ^[0-9]{2}$ ]]; then
  die "Session must be a two-digit number such as 01, not '$nn'."
fi

top=$(git rev-parse --show-toplevel 2>/dev/null) || die "Run this from inside a clone of the course repository."
cd "$top"

# Exactly one sessions/<NN>-*/exercises folder: the only path this script ever stages.
shopt -s nullglob
candidates=(sessions/"$nn"-*/exercises)
shopt -u nullglob
dirs=()
for d in "${candidates[@]}"; do
  if [ -d "$d" ] && [ ! -L "$d" ]; then dirs+=("$d"); fi
done
case ${#dirs[@]} in
  0) die "No sessions/$nn-*/exercises/ folder in this repository. Check the session number." ;;
  1) ;;
  *) die "Several folders match sessions/$nn-*/exercises/ (${dirs[*]}); refusing to guess." ;;
esac
exercises=${dirs[0]}
session_dir=${exercises%/exercises}

if ! handle=$(gh api user --jq .login); then
  die "Could not read your GitHub handle. Run 'gh auth login' first."
fi
if ! [[ $handle =~ ^[A-Za-z0-9-]+$ ]]; then
  die "Unexpected GitHub handle '$handle'; refusing to build a branch name from it."
fi
branch="homework/s$nn/$handle"
if ! [[ $branch =~ ^homework/s[0-9]{2}/[A-Za-z0-9-]+$ ]] || ! git check-ref-format "refs/heads/$branch"; then
  die "Refusing to use '$branch' as a homework branch."
fi

# --- Where the course lives and where this student may push -------------------------

origin_url=$(git config --get remote.origin.url) || die "This clone has no 'origin' remote."
trimmed=${origin_url%/}
trimmed=${trimmed%.git}
url_re='^(https://([^@/]+@)?github\.com/|ssh://git@github\.com/|git@github\.com:)([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)$'
if ! [[ $trimmed =~ $url_re ]]; then
  die "origin ($origin_url) is not a GitHub repository URL."
fi
url_prefix=${BASH_REMATCH[1]}
origin_repo=${BASH_REMATCH[3]}
# Other repos are addressed in origin's own scheme (HTTPS or SSH), so the same
# credentials work for them.
repo_url() { printf '%s%s.git' "$url_prefix" "$1"; }
repo_re='^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$'

parent_jq='(.parent // {}) as $p
  | (if ($p.nameWithOwner // "") != "" then $p.nameWithOwner
     elif ($p.name // "") != "" then "\($p.owner.login)/\($p.name)"
     else "" end) as $parent
  | "\(.nameWithOwner // "")|\($parent)|\(.viewerPermission // "")"'
if ! info=$(gh repo view "$origin_repo" --json nameWithOwner,parent,viewerPermission --jq "$parent_jq"); then
  die "Could not look up $origin_repo and your permission on it with gh."
fi
IFS='|' read -r origin_name parent permission <<<"$info"
if ! [[ $origin_name =~ $repo_re ]]; then origin_name=$origin_repo; fi

if [ -n "$parent" ]; then
  # A clone of the student's own fork: the course is the fork's parent.
  course=$parent
  push_repo=$origin_name
  push_target=origin
else
  course=$origin_name
  case $permission in
    ADMIN|MAINTAIN|WRITE)
      push_repo=$origin_name
      push_target=origin
      ;;
    "")
      die "Could not tell whether you can push to $course."
      ;;
    *)
      # No push access: fall back to the student's fork. `gh repo fork` is idempotent;
      # the fork is then identified through the API (it may be named <repo>-1), never
      # through a named remote that could point anywhere.
      note "You cannot push to $course; using your fork instead."
      gh repo fork "$course" --clone=false >/dev/null || die "Could not create or find your fork of $course."
      fork_jq=".[] | select((.owner.login | ascii_downcase) == \"${handle,,}\") | .full_name"
      attempt=1
      delay=2
      while :; do
        forks=$(gh api --paginate "repos/$course/forks" --jq "$fork_jq") || die "Could not list the forks of $course."
        if [ -n "$forks" ] || [ "$attempt" -ge 4 ]; then break; fi
        # GitHub creates forks asynchronously.
        sleep "$delay"
        attempt=$((attempt + 1))
        delay=$((delay * 2))
      done
      mapfile -t fork_list < <(printf '%s\n' "$forks" | sed '/^$/d')
      if [ "${#fork_list[@]}" -ne 1 ]; then
        die "Expected exactly one fork of $course owned by $handle, found ${#fork_list[@]} (${fork_list[*]-none})."
      fi
      push_repo=${fork_list[0]}
      push_target=$(repo_url "$push_repo")
      ;;
  esac
fi
if ! [[ $course =~ $repo_re ]] || ! [[ $push_repo =~ $repo_re ]]; then
  die "Unexpected repository names ($course, $push_repo)."
fi
if [ "$course" = "$origin_name" ]; then course_target=origin; else course_target=$(repo_url "$course"); fi

if ! default=$(gh repo view "$course" --json defaultBranchRef --jq .defaultBranchRef.name) \
    || [ -z "$default" ] || ! git check-ref-format --branch "$default" >/dev/null; then
  die "Could not read the default branch of $course."
fi

# Fetch into FETCH_HEAD only: no remote-tracking ref is rewritten.
git fetch --quiet --no-tags "$course_target" "refs/heads/$default" \
  || die "Could not fetch $default from $course."
course_tip=$(git rev-parse --verify --quiet 'FETCH_HEAD^{commit}') || die "Could not resolve $course's $default."

remote_tip=""
if ! listing=$(git ls-remote "$push_target" "refs/heads/$branch"); then
  die "Could not reach $push_repo."
fi
while read -r sha ref; do
  if [ "$ref" = "refs/heads/$branch" ]; then remote_tip=$sha; fi
done <<<"$listing"
if [ -n "$remote_tip" ]; then
  git fetch --quiet --no-tags "$push_target" "refs/heads/$branch" || die "Could not fetch $branch from $push_repo."
  remote_tip=$(git rev-parse --verify --quiet 'FETCH_HEAD^{commit}') || die "Could not resolve $branch on $push_repo."
fi

# Paths a commit changes relative to the course default that lie outside exercises/.
outside_paths() {
  git diff -z --name-only "$course_tip...$1" | while IFS= read -r -d '' path; do
    case $path in
      "$exercises"/*) ;;
      *) printf '%s\n' "$path" ;;
    esac
  done
}
assert_confined() {
  local outside
  outside=$(outside_paths "$1") || die "Could not compare $2 with $course's $default."
  if [ -n "$outside" ]; then
    die "$2 changes files outside $exercises/ (${outside//$'\n'/, }); a submission may only contain that folder. Nothing pushed."
  fi
}

# --- Switch to the homework branch -----------------------------------------------------

local_tip=$(git rev-parse --verify --quiet "refs/heads/$branch^{commit}" || true)
current=$(git symbolic-ref --quiet --short HEAD || true)

if [ -n "$local_tip" ]; then
  tip=$local_tip
  if [ -n "$remote_tip" ] && [ "$remote_tip" != "$local_tip" ]; then
    if git merge-base --is-ancestor "$local_tip" "$remote_tip"; then
      tip=$remote_tip
    elif ! git merge-base --is-ancestor "$remote_tip" "$local_tip"; then
      die "Your local $branch and the one on $push_repo have diverged. Reconcile them by hand (for example git pull --no-rebase); never force-push."
    fi
  fi
  assert_confined "$tip" "$branch"
  if [ "$current" != "$branch" ]; then
    git switch --quiet "$branch" \
      || die "Could not switch to $branch without overwriting uncommitted changes. Commit, move or discard them, then re-run."
  fi
  if [ "$tip" != "$local_tip" ]; then
    git merge --quiet --ff-only "$tip" \
      || die "Could not fast-forward $branch to $push_repo's copy without overwriting uncommitted changes."
  fi
elif [ -n "$remote_tip" ]; then
  assert_confined "$remote_tip" "$branch on $push_repo"
  git switch --quiet -c "$branch" "$remote_tip" \
    || die "Could not switch to $branch without overwriting uncommitted changes. Commit, move or discard them, then re-run."
else
  if git rev-parse --verify --quiet HEAD >/dev/null \
      && [ "$(git rev-list --count "$course_tip..HEAD")" != 0 ]; then
    die "${current:-HEAD} has commits that are not on $course's $default. A new homework branch starts from $default, so nothing unrelated is carried into a submission; switch to $default (keeping your exercises/ changes uncommitted) and re-run."
  fi
  git switch --quiet -c "$branch" "$course_tip" \
    || die "Could not switch to $branch without overwriting uncommitted changes. Commit, move or discard them, then re-run."
fi

if [ "$(git symbolic-ref --quiet --short HEAD || true)" != "$branch" ]; then
  die "Not on $branch; refusing to commit."
fi

# --- Session check, commit, push ---------------------------------------------------------

if [ -f "$exercises/turn-in-check.sh" ]; then
  note "Running $exercises/turn-in-check.sh"
  if ! (cd "$session_dir" && bash exercises/turn-in-check.sh); then
    die "The session check failed. Nothing was committed or pushed; fix the reported problem and re-run."
  fi
fi

# The pathspec keeps everything outside exercises/ out of the commit, including files the
# student (or the check) staged elsewhere. --allow-empty: every run records a submission.
git add -A -- "$exercises"
git commit --quiet --allow-empty -m "Turn in session $nn homework ($handle)" -- "$exercises" \
  || die "Could not commit $exercises/."
assert_confined HEAD "$branch"

attempt=1
delay=2
until git push --quiet "$push_target" "HEAD:refs/heads/$branch"; do
  if [ "$attempt" -ge 4 ]; then
    die "Push failed after $attempt attempts. Your submission is committed locally on $branch; re-run to push it."
  fi
  note "Push failed (attempt $attempt); retrying in ${delay}s..."
  sleep "$delay"
  attempt=$((attempt + 1))
  delay=$((delay * 2))
done

note "Turned in session $nn as $branch on $push_repo."
echo "https://github.com/$push_repo/tree/$branch"
if [ "$push_repo" != "$course" ]; then
  echo "Compare with the course: https://github.com/$course/compare/$default...${push_repo%%/*}:$branch"
fi
