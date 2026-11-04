#!/usr/bin/env bash
# CI (student-setup.yml): run the student setup twice, non-interactively, then check the result.
#
#   bash run_twice.sh SOURCE     SOURCE: a checkout of the repository at the commit under test
#
# Each run is the one-liner, `curl -fsSL <url> | bash -s -- --yes --agent both --no-login`, with
# the URL, the raw base (versions.env) and the clone URL pointing at SOURCE instead of main.
# The bash it pipes into is the one running this script: /bin/bash (3.2) on macOS. Then
# ci_verify.py checks the tools, hooks, session sync, the rerun and the clone's state.
set -euo pipefail

src=$(cd "$1" && pwd)
clone="$HOME/coding-agent-cursus"
logs="$HOME/student-setup-logs"
mkdir -p "$logs"
export CURSUS_RAW_BASE="file://$src" CURSUS_CLONE_URL="file://$src"
echo "Running the setup with $BASH ($BASH_VERSION)"

for run in first second; do
  echo "::group::$run run"
  status=0
  curl -fsSL "file://$src/setup/student/install.sh" | "$BASH" -s -- --yes --agent both --no-login 2>&1 | tee "$logs/$run.log" || status=$?
  echo "::endgroup::"
  if [ "$status" -ne 0 ]; then
    echo "The $run run failed (exit $status)."
    exit "$status"
  fi
  if [ "$run" = first ]; then
    "$HOME/.local/bin/uv" run --no-project --python 3.12 python "$src/tests/student_setup/ci_verify.py" --clone "$clone" --record "$logs/state.txt"
  fi
done

"$HOME/.local/bin/uv" run --no-project --python 3.12 python "$src/tests/student_setup/ci_verify.py" --clone "$clone" \
  --first "$logs/first.log" --second "$logs/second.log" --before "$logs/state.txt" \
  --agents claude,codex --preinstalled "${PREINSTALLED:-}"
