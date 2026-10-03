#!/usr/bin/env bash
# One-time, agent-neutral setup: activate this repo's protected-main git hooks.
#
# `main` is protected by the hooks under .githooks/, but those hooks are inert
# until core.hooksPath points at them. This script wires that up. Run it by hand
# once per clone: no agent calls it automatically (ADR 0005), so activation does
# not depend on any one agent. Safe to run repeatedly.
#
#   ./setup/git-hooks.sh
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true

echo "[setup] core.hooksPath -> .githooks (protected-main hooks active)."
