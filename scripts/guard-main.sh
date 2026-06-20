#!/usr/bin/env bash
# Shared PreToolUse guard: refuse any Bash command that would commit on, or push
# to, a protected branch (main/master), or bypass the hooks with --no-verify.
#
# Agent-independent source of truth. Both harnesses invoke this same script:
#   - Claude Code: PreToolUse(Bash) hook in .claude/settings.json
#   - Codex:       PreToolUse(Bash) hook in .codex/config.toml
# Both pass an identical JSON event on stdin (tool_name + tool_input.command) and
# both treat exit code 2 + a stderr reason as "deny", so one script serves both.
# This is convenience only — the real guarantee lives in .githooks/* and
# .github/workflows/pr-only.yml, which hold even for an agent with zero config.
#
# Tokenizes the command with shlex so heredoc bodies, commit messages, and
# echoed strings don't trigger false positives.

input=$(cat)

current_branch=$(git symbolic-ref --short HEAD 2>/dev/null || echo "")

export GUARD_EVENT_JSON="$input"
export GUARD_CURRENT_BRANCH="$current_branch"

python3 <<'PY'
import json, os, re, shlex, sys

current_branch = os.environ.get("GUARD_CURRENT_BRANCH", "")
PROTECTED = {"main", "master"}

try:
    event = json.loads(os.environ.get("GUARD_EVENT_JSON", ""))
except Exception:
    sys.exit(0)

cmd = (event.get("tool_input") or {}).get("command") or ""
if not cmd.strip():
    sys.exit(0)

def deny(msg):
    sys.stderr.write(f"[guard-main] {msg}\n")
    sys.exit(2)

# Split on shell separators that introduce a new simple command.
SEPARATORS = re.compile(r'(?:&&|\|\||;|\||\bthen\b|\bdo\b|\belse\b)')
segments = SEPARATORS.split(cmd)

def tokenize(segment):
    try:
        return shlex.split(segment, comments=False, posix=True)
    except ValueError:
        # Unbalanced quotes (e.g. inside a heredoc body) — give up on this
        # segment rather than risk a false positive.
        return []

def strip_leading_env(tokens):
    i = 0
    while i < len(tokens) and "=" in tokens[i] and not tokens[i].startswith("-"):
        # VAR=value prefix
        name = tokens[i].split("=", 1)[0]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            i += 1
            continue
        break
    return tokens[i:]

def find_git_subcommands(tokens):
    """Yield (subcommand, args) pairs for `git <sub>` invocations in tokens."""
    i = 0
    while i < len(tokens):
        if tokens[i] == "git":
            # Skip git global flags like -C path, -c key=val
            j = i + 1
            while j < len(tokens):
                t = tokens[j]
                if t in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
                    j += 2
                elif t.startswith("-"):
                    j += 1
                else:
                    break
            if j < len(tokens):
                yield tokens[j], tokens[j+1:]
                i = j + 1
                continue
        i += 1

for seg in segments:
    tokens = strip_leading_env(tokenize(seg))
    if not tokens:
        continue

    for sub, args in find_git_subcommands(tokens):
        # 1. Block commits / merges / rebases / cherry-picks while HEAD on main.
        if sub in ("commit", "merge", "cherry-pick", "rebase") and current_branch in PROTECTED:
            deny(f"Refusing 'git {sub}' while HEAD is on '{current_branch}'. Switch to a feature branch.")

        # 2. Block --no-verify on commit/push.
        if sub in ("commit", "push") and "--no-verify" in args:
            deny(f"Refusing 'git {sub} --no-verify'. Fix the hook failure rather than bypassing it.")

        # 3. Block pushes that target main/master.
        if sub == "push":
            force = any(a in ("--force", "-f", "--force-with-lease") for a in args)
            # Strip flags to find positional args (remote + refspecs).
            positionals = []
            skip_next = False
            for a in args:
                if skip_next:
                    skip_next = False
                    continue
                if a in ("-o", "--push-option", "--receive-pack", "--repo",
                         "--signed", "--exec"):
                    skip_next = True
                    continue
                if a.startswith("-"):
                    continue
                positionals.append(a)

            # First positional is the remote; subsequent are refspecs.
            refspecs = positionals[1:] if len(positionals) > 1 else []

            def targets_protected(refspec):
                # refspec forms: "main", "HEAD:main", "feat:refs/heads/main",
                # "+main", "src:dst". The destination is the part after ':'
                # (or the whole thing if no colon).
                spec = refspec.lstrip("+")
                dst = spec.split(":", 1)[1] if ":" in spec else spec
                dst = dst.removeprefix("refs/heads/")
                return dst in PROTECTED

            hit = any(targets_protected(r) for r in refspecs)
            # If no refspec was given, `git push` pushes the current branch —
            # safe unless we're currently on main (already covered by hook
            # configuration and the commit guard).
            if hit:
                if force:
                    deny("Refusing force-push targeting main/master.")
                deny("Refusing direct push to main/master. Use /ship to open a PR.")

sys.exit(0)
PY
