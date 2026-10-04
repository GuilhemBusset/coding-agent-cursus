#!/usr/bin/env bash
# Offline behavioural acceptance check for the Session 1 setup helper.
# Run from any directory using this script's path. No tools are installed.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
helper="$repo_root/setup/session-01-fundamentals.sh"
session_dir="$repo_root/sessions/01-fundamentals"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

fail() { echo "[test-session-01] FAIL: $*" >&2; exit 1; }
pass() { echo "[test-session-01] ok: $*"; }

[[ -f "$helper" ]] || fail "missing setup/session-01-fundamentals.sh"
bash -n "$helper"
mkdir -p "$tmp/bin" "$tmp/unrelated working directory"
export SESSION_SETUP_LOG="$tmp/mise.log"
cat > "$tmp/bin/mise" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
printf '%s|%s\n' "$PWD" "$*" >> "$SESSION_SETUP_LOG"
if [[ "${SESSION_SETUP_FAIL_INSTALL:-0}" == 1 && "$*" == install ]]; then
  exit 23
fi
STUB
chmod +x "$tmp/bin/mise"
export PATH="$tmp/bin:$PATH"

check_log() {
  local expected_dir="$1"
  local actual expected
  expected="$(printf '%s|%s\n' \
    "$expected_dir" 'trust mise.toml' \
    "$expected_dir" 'install' \
    "$expected_dir" 'exec -- uv sync --locked')"
  actual="$(cat "$SESSION_SETUP_LOG")"
  [[ "$actual" == "$expected" ]] || fail "expected trust, install, locked sync in $expected_dir; got: $actual"
}

# Both invocations promised by the runbooks must target the same session.
: > "$SESSION_SETUP_LOG"
(cd "$tmp/unrelated working directory" && bash "$helper")
check_log "$session_dir"
pass "absolute invocation from an unrelated directory"

: > "$SESSION_SETUP_LOG"
(cd "$repo_root" && bash setup/session-01-fundamentals.sh)
check_log "$session_dir"
pass "relative invocation from the repo root"

# Relocate just the helper: catches hard-coded checkout paths and unquoted paths.
relocated="$tmp/clone with spaces"
mkdir -p "$relocated/setup" "$relocated/sessions/01-fundamentals"
cp "$helper" "$relocated/setup/session-01-fundamentals.sh"
: > "$SESSION_SETUP_LOG"
(cd "$tmp/unrelated working directory" && bash "$relocated/setup/session-01-fundamentals.sh")
check_log "$relocated/sessions/01-fundamentals"
pass "location resolved from the helper in a relocated checkout"

# A failed install must fail setup and never proceed to sync.
: > "$SESSION_SETUP_LOG"
if (cd "$tmp/unrelated working directory" && SESSION_SETUP_FAIL_INSTALL=1 bash "$helper"); then
  fail "setup succeeded after mise install failed"
fi
expected_failure="$(printf '%s|%s\n' "$session_dir" 'trust mise.toml' "$session_dir" 'install')"
[[ "$(cat "$SESSION_SETUP_LOG")" == "$expected_failure" ]] || fail "setup continued after failed install"
pass "installation errors propagate"

for readme in "$repo_root/setup/README.md" "$session_dir/README.md"; do
  grep -Fq 'setup/session-01-fundamentals.sh' "$readme" || fail "$readme must document the helper"
done
pass "both runbooks document the helper"
echo "[test-session-01] all checks passed"
