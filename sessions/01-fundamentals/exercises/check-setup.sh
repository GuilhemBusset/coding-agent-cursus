#!/usr/bin/env bash
# Session 1 pre-work: check that this machine is ready for the session.
# Instructions: 00-prework.html in this folder, section "Check your setup".
#
# macOS, Linux, WSL, or Git Bash on Windows, from the root of your course clone:
#
#   bash sessions/01-fundamentals/exercises/check-setup.sh
#
# (In Windows PowerShell, use check-setup.ps1 next to this file instead.)
#
# The checks live in check_setup.py next to this file, which runs with Python 3.12
# through uv. It prints PASS or FAIL for each tool, the network, your GitHub login, a
# push to a temporary branch setup-check/<your handle> (deleted straight after), and a
# smoke test of whichever agent you have, then a summary block to paste into the form
# your instructor gives you. It exits non-zero if anything FAILs. It never prints a
# secret. If uv is missing or cannot start the checker, this script still reports which
# tools it can find, prints the summary block and exits non-zero.
set -u

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

echo "Checking your setup for Session 1. The agent smoke test can take a minute or two."

os_name() {
  local version=""
  case "$(uname -s 2>/dev/null)" in
    Linux)
      if [ -r /proc/version ]; then version=$(</proc/version); fi
      if [ -n "${WSL_DISTRO_NAME:-}" ] || [[ $version == *[Mm]icrosoft* ]]; then
        echo "Linux (WSL)"
      else
        echo "Linux"
      fi
      ;;
    Darwin) echo "macOS" ;;
    MINGW* | MSYS* | CYGWIN*) echo "Windows" ;;
    *) echo "unknown" ;;
  esac
}

# Presence-only report for when the Python checker could not run at all.
fallback() {
  local lines=("$1") name agents="" failures=0 line
  for name in git gh mise; do
    if command -v "$name" >/dev/null 2>&1; then
      lines+=("$name: PASS found (version not checked)")
    else
      lines+=("$name: FAIL not found on PATH; see 'Install the tools' on the pre-work page")
    fi
  done
  for name in claude codex; do
    if command -v "$name" >/dev/null 2>&1; then
      lines+=("$name: PASS found (not smoke-tested)")
      agents="${agents:+$agents and }$name"
    else
      lines+=("$name: not installed (fine)")
    fi
  done
  if [ -n "$agents" ]; then
    lines+=("agent: PASS found $agents")
  else
    lines+=("agent: FAIL neither Claude Code nor Codex is installed")
  fi
  for line in "${lines[@]}"; do
    echo "$line"
    case $line in *": FAIL"*) failures=$((failures + 1)) ;; esac
  done
  echo "----- BEGIN SETUP SUMMARY -----"
  echo "date: $(date -u +%Y-%m-%d) (UTC)"
  echo "os: $(os_name)"
  echo "github: unknown"
  printf '%s\n' "${lines[@]}"
  echo "result: FAIL ($failures FAIL)"
  echo "----- END SETUP SUMMARY -----"
  exit 1
}

if ! command -v uv >/dev/null 2>&1; then
  fallback "uv: FAIL not found on PATH; install uv (see 'Install the tools' on the pre-work page), open a new terminal and rerun"
fi

# uv's own messages (for example a first-time Python download) go to stderr and are
# not shown; the checker prints everything it reports on stdout. Its exit status is
# passed on only if it printed its summary block: Python that fails to start can also
# exit 1, and then this script reports instead.
uv run --no-project --python 3.12 python "$here/check_setup.py" 2>/dev/null | {
  reported=1
  while IFS= read -r line || [ -n "$line" ]; do
    printf '%s\n' "$line"
    if [ "${line%$'\r'}" = "----- END SETUP SUMMARY -----" ]; then reported=0; fi
  done
  exit "$reported"
}
statuses=("${PIPESTATUS[@]}")
status=${statuses[0]}
if [ "${statuses[1]}" -eq 0 ]; then
  case $status in
    0 | 1) exit "$status" ;;
  esac
fi
fallback "checker: FAIL could not start the checker through uv (exit $status); run 'uv run --no-project --python 3.12 python --version' to see why"
