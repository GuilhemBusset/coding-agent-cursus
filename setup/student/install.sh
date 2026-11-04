#!/usr/bin/env bash
# Student setup for macOS, Linux and WSL: from a fresh machine to a ready course clone.
# Instructions: setup/student/README.md. On Windows (PowerShell), use install.ps1 instead.
#
#   curl -fsSL https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.sh | bash
#   bash setup/student/install.sh [options]          # the same, from a clone
#
# It shows a plan and asks once, then installs what is missing: git and gh (from the system's
# packages, or on macOS the Xcode Command Line Tools and Homebrew or GitHub's release archive),
# uv and mise (official installers, pinned in versions.env), and Claude Code, Codex or both
# (official native installers). Then it sets your git identity, logs you in to GitHub and to
# your agent in the browser, clones the course (or reuses this clone), and runs prepare.py: git
# hooks, every session synced from its lockfile, and the setup check. A tool already at or
# above its floor is left alone. Rerunning it is safe: it skips what is done.
#
# Options (each also as an environment variable, for `curl ... | bash`):
#   --yes          CURSUS_YES=1        do not ask to confirm the plan
#   --agent A      CURSUS_AGENT=A      claude, codex or both (otherwise it asks)
#   --no-login     CURSUS_NO_LOGIN=1   skip the logins and the setup check (step 6 and 9)
#   --dry-run      CURSUS_DRY_RUN=1    print the plan and change nothing
#   --dir DIR      CURSUS_DIR=DIR      where to clone (default ~/coding-agent-cursus)
#
# Written for Bash 3.2, the /bin/bash macOS ships: no associative arrays, ${var,,} or mapfile.
# Everything runs inside main(), so bash has read the whole script before anything runs and
# no command can swallow the rest of it from a piped stdin.

say() { printf '[setup] %s\n' "$*"; }
note() { printf "           %s\n" "$*"; }
fail() {
  printf '[setup] FAILED at %s: %s\n' "$1" "$2"
  if [ -n "${3:-}" ]; then printf '[setup] Next: %s\n' "$3"; fi
  printf '[setup] Then rerun the same command; it continues from there.\n'
  exit 1
}
have() { command -v "$1" >/dev/null 2>&1; }
truthy() {
  case "${1:-}" in 1 | true | TRUE | True | yes | YES | Yes | y) return 0 ;; *) return 1 ;; esac
}
# Is there a terminal to ask on? With `curl | bash` stdin is the script, so ask on /dev/tty.
tty_ok() { (: </dev/tty) 2>/dev/null; }
ask() { # prompt -> REPLY
  printf '%s' "$1" >/dev/tty
  IFS= read -r REPLY </dev/tty || REPLY=""
}

# The first X.Y.Z (or X.Y) in a tool's --version output, as X.Y.Z; empty if it does not run.
version_of() {
  local out re='([0-9]+)\.([0-9]+)(\.([0-9]+))?'
  out=$("$1" --version 2>/dev/null </dev/null) || return 0
  out=${out%%$'\n'*}
  if [[ $out =~ $re ]]; then
    printf '%s.%s.%s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "${BASH_REMATCH[4]:-0}"
  fi
}
version_ge() { # a b: is a >= b
  local a1 a2 a3 b1 b2 b3
  IFS=. read -r a1 a2 a3 <<EOF
$1
EOF
  IFS=. read -r b1 b2 b3 <<EOF
$2
EOF
  a1=${a1:-0} a2=${a2:-0} a3=${a3:-0} b1=${b1:-0} b2=${b2:-0} b3=${b3:-0}
  if [ "$a1" -ne "$b1" ]; then [ "$a1" -gt "$b1" ]; return; fi
  if [ "$a2" -ne "$b2" ]; then [ "$a2" -gt "$b2" ]; return; fi
  [ "$a3" -ge "$b3" ]
}
fetch() { # url -> stdout
  if have curl; then
    curl -fsSL --retry 3 "$1"
  elif have wget; then
    wget -qO- "$1"
  else
    return 1
  fi
}
# Shell startup files the official installers may edit, with a checksum each.
rc_state() {
  local f
  for f in .profile .bashrc .bash_profile .zshrc .zprofile .zshenv .config/fish/config.fish; do
    if [ -f "$HOME/$f" ]; then printf '%s %s\n' "$f" "$(cksum <"$HOME/$f")"; else printf '%s -\n' "$f"; fi
  done
}
rc_changes() { # before after -> "~/.zshrc ~/.bashrc"
  local changed="" line f
  while IFS= read -r line; do
    f=${line%% *}
    case "$1" in *"$line"*) ;; *) changed="$changed ~/$f" ;; esac
  done <<EOF
$2
EOF
  printf '%s' "${changed# }"
}

usage() { sed -n '2,24p' "${BASH_SOURCE[0]:-/dev/null}" 2>/dev/null | sed 's/^# \{0,1\}//'; }

main() {
  local yes agent no_login dry_run dir
  yes=${CURSUS_YES:-}
  agent=${CURSUS_AGENT:-}
  no_login=${CURSUS_NO_LOGIN:-}
  dry_run=${CURSUS_DRY_RUN:-}
  dir=${CURSUS_DIR:-}
  while [ $# -gt 0 ]; do
    case $1 in
      -y | --yes) yes=1 ;;
      --agent) agent=${2:-}; shift ;;
      --agent=*) agent=${1#*=} ;;
      --no-login) no_login=1 ;;
      --dry-run) dry_run=1 ;;
      --dir) dir=${2:-}; shift ;;
      --dir=*) dir=${1#*=} ;;
      -h | --help) usage; return 0 ;;
      *) fail "options" "unknown option '$1'" "bash install.sh --help" ;;
    esac
    shift
  done
  truthy "$yes" && yes=1 || yes=""
  truthy "$no_login" && no_login=1 || no_login=""
  truthy "$dry_run" && dry_run=1 || dry_run=""
  case $agent in "" | claude | codex | both) ;; *) fail "options" "--agent must be claude, codex or both, not '$agent'" "rerun with --agent claude, --agent codex or --agent both" ;; esac

  local repo raw_base clone_url sysroot self_dir self_repo src
  repo=${CURSUS_REPO:-GuilhemBusset/coding-agent-cursus}
  raw_base=${CURSUS_RAW_BASE:-https://raw.githubusercontent.com/$repo/main}
  clone_url=${CURSUS_CLONE_URL:-https://github.com/$repo.git}
  # Where /etc/os-release and /proc/version are read from; the tests point it at a fixture.
  sysroot=${CURSUS_SYSROOT:-}
  self_dir="" self_repo=""
  src=${BASH_SOURCE[0]:-}
  if [ -n "$src" ] && [ -f "$src" ]; then self_dir=$(cd "$(dirname "$src")" && pwd); fi
  if [ -n "$self_dir" ] && [ -f "$self_dir/prepare.py" ] && [ -e "$self_dir/../../.git" ]; then
    self_repo=$(cd "$self_dir/../.." && pwd)
  fi
  # Tools the official installers put in ~/.local/bin count even before a new terminal. The
  # installers themselves run with the original PATH, so that they still add ~/.local/bin to
  # the shell's startup files when it is missing there.
  local orig_path=$PATH
  case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$PATH:$HOME/.local/bin" ;; esac
  export PATH

  # --- Pins and floors -------------------------------------------------------------------
  local versions key val
  local UV_VERSION="" MISE_VERSION="" GH_VERSION="" GH_MACOS_ARM64_SHA256="" GH_MACOS_AMD64_SHA256=""
  local GIT_FLOOR="" GH_FLOOR="" UV_FLOOR="" MISE_FLOOR=""
  if [ -n "$self_dir" ] && [ -f "$self_dir/versions.env" ]; then
    versions=$(cat "$self_dir/versions.env")
  else
    versions=$(fetch "$raw_base/setup/student/versions.env") ||
      fail "plan" "could not download $raw_base/setup/student/versions.env" "check your network connection"
  fi
  while IFS= read -r line; do
    case $line in "" | "#"*) continue ;; esac
    key=${line%%=*} val=${line#*=}
    case $key in
      UV_VERSION | MISE_VERSION | GH_VERSION | GH_MACOS_ARM64_SHA256 | GH_MACOS_AMD64_SHA256 | GIT_FLOOR | GH_FLOOR | UV_FLOOR | MISE_FLOOR)
        eval "$key=\$val" ;;
    esac
  done <<EOF
$versions
EOF
  for key in UV_VERSION MISE_VERSION GH_VERSION GIT_FLOOR GH_FLOOR UV_FLOOR MISE_FLOOR; do
    eval "val=\${$key}"
    [ -n "$val" ] || fail "plan" "versions.env has no $key" "report this to your instructor"
  done

  # --- 1. Plan: platform and track ---------------------------------------------------------
  local os arch track pm="" wsl="" distro="" id="" id_like="" pretty="" pv="" sudo=""
  os=$(uname -s)
  arch=$(uname -m)
  case $os in
    Darwin) track="macOS" distro="macOS $(sw_vers -productVersion 2>/dev/null </dev/null)" ;;
    Linux)
      if [ -r "$sysroot/proc/version" ]; then pv=$(cat "$sysroot/proc/version"); fi
      case $pv in *[Mm]icrosoft* | *WSL*) wsl=1 ;; esac
      for f in "$sysroot/etc/os-release" "$sysroot/usr/lib/os-release"; do
        [ -r "$f" ] || continue
        while IFS= read -r line; do
          val=${line#*=} val=${val#\"} val=${val%\"}
          case $line in ID=*) id=$val ;; ID_LIKE=*) id_like=$val ;; PRETTY_NAME=*) pretty=$val ;; esac
        done <"$f"
        break
      done
      distro=${pretty:-${id:-unknown Linux}}
      case " $id $id_like " in
        *" debian "* | *" ubuntu "*) pm=apt track="Debian / Ubuntu" ;;
        *" arch "*) pm=pacman track="Arch" ;;
        *)
          if [ "$id" = fedora ]; then pm=dnf track="Fedora"; else track="other Linux"; fi ;;
      esac
      if [ -n "$wsl" ]; then track="Windows with WSL 2, $track"; fi
      ;;
    *) fail "plan" "install.sh is for macOS, Linux and WSL, not $os" "on Windows, use install.ps1 (see setup/student/README.md)" ;;
  esac
  if [ "$(id -u)" != 0 ]; then sudo=sudo; fi

  # Which tools are there, at which version.
  local t v
  for t in git gh curl uv mise claude codex; do
    v=""
    if have "$t"; then
      v=$(version_of "$t")
      # macOS ships /usr/bin/git as a stub that opens the Command Line Tools dialog.
      if [ "$t" = git ] && [ "$os" = Darwin ] && ! xcode-select -p >/dev/null 2>&1; then v=""; fi
    fi
    eval "have_$t=\$v"
  done
  ok() { # tool floor: present and at or above the floor
    local v
    eval "v=\${have_$1}"
    [ -n "$v" ] && { [ -z "${2:-}" ] || version_ge "$v" "$2"; }
  }

  # What is missing, and how each missing tool is installed.
  local need_git="" need_gh="" need_pkgs="" sys_cmds="" gh_how=""
  ok git "$GIT_FLOOR" || need_git=1
  ok gh "$GH_FLOOR" || need_gh=1
  say "Course setup for the $track track (${distro:+$distro, }$arch)."
  local agents=""
  case $agent in claude) agents=claude ;; codex) agents=codex ;; both) agents="claude codex" ;; esac
  if [ -z "$agent" ] && [ -z "$dry_run" ]; then
    if ! tty_ok; then
      fail "agent" "no terminal to ask which agent to install" "rerun with --agent claude, --agent codex or --agent both (CURSUS_AGENT=...)"
    fi
    while [ -z "$agents" ]; do
      ask "[setup] Which agent do you use? 1) Claude Code  2) Codex  3) both [1/2/3]: "
      case $REPLY in 1 | claude) agent=claude agents=claude ;; 2 | codex) agent=codex agents=codex ;; 3 | both) agent=both agents="claude codex" ;; esac
    done
  fi
  if [ -z "$agents" ]; then agents="claude codex"; fi

  # What the official installers below need besides a shell: curl, tar, gzip and awk.
  local p_curl="" p_tar="" p_gzip="" p_awk=""
  have curl || p_curl=1
  have tar || p_tar=1
  have gzip || p_gzip=1
  have awk || p_awk=1
  case $pm in
    apt)
      if [ -n "$need_git" ]; then need_pkgs="$need_pkgs git"; fi
      if [ -n "$p_curl" ]; then need_pkgs="$need_pkgs curl ca-certificates"; fi
      if [ -n "$p_tar" ]; then need_pkgs="$need_pkgs tar"; fi
      if [ -n "$p_gzip" ]; then need_pkgs="$need_pkgs gzip"; fi
      if [ -n "$p_awk" ]; then need_pkgs="$need_pkgs gawk"; fi
      if [ -n "$need_pkgs" ] || [ -n "$need_gh" ]; then sys_cmds="$sudo apt-get update"; fi
      if [ -n "$need_pkgs" ]; then sys_cmds="$sys_cmds
$sudo apt-get install -y$need_pkgs"; fi
      if [ -n "$need_gh" ]; then
        gh_how="GitHub's apt repository (https://cli.github.com/packages), into /usr/bin"
        sys_cmds="$sys_cmds
$sudo mkdir -p -m 755 /etc/apt/keyrings /etc/apt/sources.list.d
$sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg (GitHub CLI's signing key)
$sudo tee /etc/apt/sources.list.d/github-cli.list (GitHub CLI's apt repository)
$sudo apt-get update
$sudo apt-get install -y gh"
      fi
      ;;
    dnf)
      if [ -n "$need_git" ]; then need_pkgs="$need_pkgs git"; fi
      if [ -n "$p_curl" ]; then need_pkgs="$need_pkgs curl"; fi
      if [ -n "$p_tar" ]; then need_pkgs="$need_pkgs tar"; fi
      if [ -n "$p_gzip" ]; then need_pkgs="$need_pkgs gzip"; fi
      if [ -n "$p_awk" ]; then need_pkgs="$need_pkgs gawk"; fi
      if [ -n "$need_pkgs" ]; then sys_cmds="$sudo dnf install -y$need_pkgs"; fi
      if [ -n "$need_gh" ]; then
        gh_how="GitHub's rpm repository (https://cli.github.com/packages/rpm/gh-cli.repo), into /usr/bin"
        sys_cmds="${sys_cmds:+$sys_cmds
}$sudo dnf install -y dnf5-plugins
$sudo dnf config-manager addrepo --from-repofile=https://cli.github.com/packages/rpm/gh-cli.repo
$sudo dnf install -y gh"
      fi
      ;;
    pacman)
      if [ -n "$need_git" ]; then need_pkgs="$need_pkgs git"; fi
      if [ -n "$need_gh" ]; then need_pkgs="$need_pkgs github-cli"; gh_how="pacman (github-cli), into /usr/bin"; fi
      if [ -n "$p_curl" ]; then need_pkgs="$need_pkgs curl"; fi
      if [ -n "$p_tar" ]; then need_pkgs="$need_pkgs tar"; fi
      if [ -n "$p_gzip" ]; then need_pkgs="$need_pkgs gzip"; fi
      if [ -n "$p_awk" ]; then need_pkgs="$need_pkgs gawk"; fi
      if [ -n "$need_pkgs" ]; then
        if [ ! -f "$sysroot/var/lib/pacman/sync/core.db" ]; then sys_cmds="$sudo pacman -Sy --noconfirm
"; fi
        sys_cmds="$sys_cmds$sudo pacman -S --needed --noconfirm$need_pkgs"
      fi
      ;;
  esac
  local mac_gh_arch="" mac_gh_sha=""
  if [ "$os" = Darwin ] && [ -n "$need_gh" ]; then
    if have brew; then
      gh_how="Homebrew (brew install gh), into Homebrew's bin folder"
    else
      case $arch in arm64) mac_gh_arch=arm64 mac_gh_sha=$GH_MACOS_ARM64_SHA256 ;; *) mac_gh_arch=amd64 mac_gh_sha=$GH_MACOS_AMD64_SHA256 ;; esac
      gh_how="GitHub's release archive gh_${GH_VERSION}_macOS_${mac_gh_arch}.zip (SHA-256 checked), into ~/.local/share/coding-agent-cursus/gh/$GH_VERSION, linked as ~/.local/bin/gh"
    fi
  fi

  # The clone: this one, an existing one at --dir, or a new one.
  local clone clone_how
  if [ -n "$self_repo" ]; then
    clone=$self_repo clone_how="reuse the clone this script runs from, as it is"
  else
    clone=${dir:-$HOME/coding-agent-cursus}
    case $clone in /*) ;; *) clone="$(pwd)/$clone" ;; esac
    if [ -e "$clone/.git" ]; then clone_how="reuse the existing clone, as it is"; else clone_how="git clone $clone_url"; fi
  fi

  say "Plan (nothing has changed yet):"
  line_for() { # tool floor how-if-missing
    local v
    eval "v=\${have_$1}"
    if [ -n "$v" ] && { [ -z "$2" ] || version_ge "$v" "$2"; }; then
      printf '  %-8s present %s%s, left alone\n' "$1" "$v" "${2:+ (>= $2)}"
    elif [ -n "$v" ]; then
      printf '  %-8s present %s, below the floor %s: install %s\n' "$1" "$v" "$2" "$3"
    else
      printf '  %-8s missing: install %s\n' "$1" "$3"
    fi
  }
  local git_how gh_line
  case $os in
    Darwin) git_how="Apple's Xcode Command Line Tools (xcode-select --install opens a dialog)" ;;
    *) case $pm in "") git_how="(no supported package manager: see below)" ;; *) git_how="$pm, into /usr/bin" ;; esac ;;
  esac
  gh_line=${gh_how:-"(no supported package manager: see below)"}
  line_for git "$GIT_FLOOR" "$git_how"
  line_for gh "$GH_FLOOR" "$gh_line"
  line_for uv "$UV_FLOOR" "uv $UV_VERSION from https://astral.sh/uv/$UV_VERSION/install.sh, into ~/.local/bin"
  line_for mise "$MISE_FLOOR" "mise $MISE_VERSION from https://mise.run, into ~/.local/bin"
  for t in $agents; do
    case $t in
      claude) line_for claude "" "the current Claude Code from https://claude.ai/install.sh, into ~/.local/bin and ~/.local/share/claude" ;;
      codex) line_for codex "" "the current Codex from https://chatgpt.com/codex/install.sh, into ~/.local/bin and ~/.codex" ;;
    esac
  done
  if [ -z "$agent" ]; then note "(it asks which agent you use: Claude Code, Codex or both)"; fi
  printf '  %-8s %s\n' "identity" "your git user.name and user.email: asked for if not set"
  if [ -n "$no_login" ]; then
    printf '  %-8s %s\n' "logins" "skipped (--no-login), and so is the setup check"
  else
    printf '  %-8s %s\n' "logins" "GitHub (gh auth login) then your agent, in the browser, if not logged in yet"
  fi
  printf '  %-8s %s\n' "clone" "$clone: $clone_how"
  printf '  %-8s %s\n' "prepare" "git hooks, then mise trust, mise install, mise exec -- uv sync --locked in every session"
  if [ -z "$no_login" ]; then printf '  %-8s %s\n' "check" "the latest session's setup check, with its summary block"; fi
  if [ -n "$wsl" ]; then
    case $clone in /mnt/*) say "Warning: $clone is on the Windows drive (/mnt/...). Keep the clone in the Linux filesystem: rerun with --dir ~/coding-agent-cursus." ;; esac
  fi
  if [ -n "$sys_cmds" ]; then
    if [ -n "$sudo" ]; then say "These commands use sudo and may ask for your password:"; else say "These commands install system packages (as root):"; fi
    printf '%s\n' "$sys_cmds" | sed 's/^/  /'
  fi
  if [ "$os" = Darwin ] && [ -n "$need_git" ]; then say "git: a macOS dialog asks to install the Command Line Tools; finish it, then rerun this command."; fi
  if [ -z "$pm" ] && [ "$os" != Darwin ] && { [ -n "$need_git" ] || [ -n "$need_gh" ] || [ -n "$p_curl" ]; }; then
    say "This setup cannot install git, gh or curl on this distribution: it stops at that step."
  fi
  if [ -n "${ANTHROPIC_API_KEY+set}" ]; then
    say "Note: ANTHROPIC_API_KEY is set (value hidden). Claude Code uses it instead of your subscription; see 'Login troubleshooting' on the pre-work page."
  fi

  if [ -n "$dry_run" ]; then
    say "Dry run: nothing was installed, written or changed."
    return 0
  fi
  if ! tty_ok && ! { [ -n "$yes" ] && [ -n "$no_login" ]; }; then
    fail "plan" "no terminal to ask on (the logins need one)" "run it from a terminal, or non-interactively with --yes --agent <a> --no-login"
  fi
  if [ -z "$yes" ]; then
    ask "[setup] Go ahead? [Y/n] "
    case $REPLY in "" | y | Y | yes | Yes) ;; *) say "Stopped: nothing was changed."; return 0 ;; esac
  fi

  local work log before after
  work=$(mktemp -d "${TMPDIR:-/tmp}/cursus-setup.XXXXXX") || fail "plan" "cannot create a temporary folder" "check that ${TMPDIR:-/tmp} is writable"
  # shellcheck disable=SC2064 # expand $work now, while it is set.
  trap "rm -rf '$work'" EXIT
  # Runs an installer with its output in a log; on failure, shows the end of it.
  quiet() { # name command...
    log="$work/$1.log"
    shift
    if "$@" >"$log" 2>&1 </dev/null; then return 0; fi
    tail -n 15 "$log" | sed 's/^/  | /'
    return 1
  }
  sudo_ok() {
    [ -z "$sudo" ] || have sudo || fail "system tools" "sudo is not available, and installing $1 needs it" "install $1 as an administrator: see 'Install the tools' on the pre-work page, sessions/01-fundamentals/exercises/00-prework.html"
  }
  as_root() { if [ -n "$sudo" ]; then sudo "$@"; else "$@"; fi; }

  # --- 2. System tools ---------------------------------------------------------------------
  if [ "$os" = Darwin ]; then
    if [ -n "$need_git" ]; then
      if xcode-select -p >/dev/null 2>&1; then
        fail "system tools" "git ${have_git:-?} is below the floor $GIT_FLOOR" "softwareupdate --list, then install the Command Line Tools update it offers"
      fi
      xcode-select --install >/dev/null 2>&1 </dev/null || true
      say "git: a macOS dialog now asks to install the Command Line Tools (which include git)."
      say "Paused, not failed: finish that dialog, then rerun the same command. It continues from there."
      return 0
    fi
    say "git: present ${have_git} (>= $GIT_FLOOR), left alone"
    if [ -n "$need_gh" ]; then
      if have brew; then
        say "gh: installing with Homebrew (brew install gh)"
        quiet gh brew install gh || fail "system tools" "brew install gh failed (log above)" "brew install gh"
      else
        say "gh: installing $GH_VERSION from GitHub's release archive"
        local zip="gh_${GH_VERSION}_macOS_${mac_gh_arch}" dest="$HOME/.local/share/coding-agent-cursus/gh/$GH_VERSION"
        curl -fsSL --retry 3 -o "$work/$zip.zip" "https://github.com/cli/cli/releases/download/v$GH_VERSION/$zip.zip" </dev/null ||
          fail "system tools" "could not download $zip.zip" "check your network, or install gh from https://github.com/cli/cli/blob/trunk/docs/install_macos.md"
        [ "$(shasum -a 256 "$work/$zip.zip" | cut -d' ' -f1)" = "$mac_gh_sha" ] ||
          fail "system tools" "$zip.zip does not match its pinned SHA-256; nothing installed" "rerun later, or install gh from https://github.com/cli/cli/blob/trunk/docs/install_macos.md"
        (cd "$work" && unzip -q "$zip.zip") || fail "system tools" "could not unpack $zip.zip" "rerun the same command"
        if ! { rm -rf "$dest" && mkdir -p "$(dirname "$dest")" "$HOME/.local/bin" && mv "$work/$zip" "$dest" &&
          ln -sfn "$dest/bin/gh" "$HOME/.local/bin/gh"; }; then
          fail "system tools" "could not install gh into $dest" "check that ~/.local is writable"
        fi
      fi
      have_gh=$(version_of gh)
      [ -n "$have_gh" ] || fail "system tools" "gh was installed but does not run" "open a new terminal and run gh --version"
      say "gh: installed $have_gh"
    else
      say "gh: present ${have_gh} (>= $GH_FLOOR), left alone"
    fi
  elif [ -z "$pm" ]; then
    if [ -n "$need_git" ] || [ -n "$need_gh" ] || [ -n "$p_curl" ]; then
      fail "system tools" "this setup does not know how to install packages on $distro" "install git, gh and curl yourself (https://git-scm.com/install/linux, https://github.com/cli/cli/blob/trunk/docs/install_linux.md, or 'Install the tools' on the pre-work page), then rerun"
    fi
  elif [ -n "$sys_cmds" ]; then
    sudo_ok "${need_pkgs# }${need_gh:+ gh}"
    say "system packages: installing with $pm${sudo:+ (sudo may ask for your password)}"
    case $pm in
      apt)
        quiet apt-update as_root env DEBIAN_FRONTEND=noninteractive apt-get update || fail "system tools" "apt-get update failed (log above)" "sudo apt-get update"
        if [ -n "$need_pkgs" ]; then
          # shellcheck disable=SC2086 # one word per package
          quiet apt-install as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y $need_pkgs ||
            fail "system tools" "apt-get install failed (log above)" "sudo apt-get install -y$need_pkgs"
        fi
        if [ -n "$need_gh" ]; then
          { as_root mkdir -p -m 755 /etc/apt/keyrings /etc/apt/sources.list.d &&
            curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | as_root tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null &&
            as_root chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg &&
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | as_root tee /etc/apt/sources.list.d/github-cli.list >/dev/null; } </dev/null ||
            fail "system tools" "could not add GitHub CLI's apt repository" "follow https://github.com/cli/cli/blob/trunk/docs/install_linux.md#debian"
          if ! { quiet gh-update as_root env DEBIAN_FRONTEND=noninteractive apt-get update &&
            quiet gh-install as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y gh; }; then
            fail "system tools" "apt-get install gh failed (log above)" "sudo apt-get update && sudo apt-get install -y gh"
          fi
        fi
        ;;
      dnf)
        if [ -n "$need_pkgs" ]; then
          # shellcheck disable=SC2086 # one word per package
          quiet dnf-install as_root dnf install -y $need_pkgs || fail "system tools" "dnf install failed (log above)" "sudo dnf install -y$need_pkgs"
        fi
        if [ -n "$need_gh" ]; then
          quiet dnf-plugins as_root dnf install -y dnf5-plugins || fail "system tools" "dnf install dnf5-plugins failed (log above)" "sudo dnf install -y dnf5-plugins"
          if [ ! -f /etc/yum.repos.d/gh-cli.repo ]; then
            quiet gh-repo as_root dnf config-manager addrepo --from-repofile=https://cli.github.com/packages/rpm/gh-cli.repo ||
              fail "system tools" "could not add GitHub CLI's rpm repository (log above)" "sudo dnf config-manager addrepo --from-repofile=https://cli.github.com/packages/rpm/gh-cli.repo"
          fi
          quiet gh-install as_root dnf install -y gh || fail "system tools" "dnf install gh failed (log above)" "sudo dnf install -y gh"
        fi
        ;;
      pacman)
        if [ ! -f /var/lib/pacman/sync/core.db ]; then
          quiet pacman-sync as_root pacman -Sy --noconfirm || fail "system tools" "pacman -Sy failed (log above)" "sudo pacman -Sy"
        fi
        # shellcheck disable=SC2086 # one word per package
        quiet pacman-install as_root pacman -S --needed --noconfirm $need_pkgs ||
          fail "system tools" "pacman -S failed (log above); if a package was not found, update the system first" "sudo pacman -Syu, then rerun"
        ;;
    esac
  fi
  if [ "$os" != Darwin ]; then
    local was floor
    for t in git gh; do
      v=$(version_of "$t")
      eval "was=\${have_$t}"
      if [ -z "$v" ]; then fail "system tools" "$t is still not installed" "see 'Install the tools' on the pre-work page"; fi
      if [ "$t" = git ]; then floor=$GIT_FLOOR; else floor=$GH_FLOOR; fi
      if [ "$v" = "$was" ]; then
        say "$t: present $v (>= $floor), left alone"
      else
        say "$t: installed $v"
      fi
      eval "have_$t=\$v"
    done
    have curl || fail "system tools" "curl is still not installed" "install curl with your package manager, then rerun"
  fi

  # --- 3. User tools: uv and mise, official installers at the pinned versions --------------
  before=$(rc_state)
  if ok uv "$UV_FLOOR"; then
    say "uv: present $have_uv (>= $UV_FLOOR), left alone"
  else
    say "uv: installing $UV_VERSION from https://astral.sh/uv/$UV_VERSION/install.sh"
    quiet uv env PATH="$orig_path" sh -c "curl -LsSf https://astral.sh/uv/$UV_VERSION/install.sh | sh" ||
      fail "user tools" "the uv installer failed (log above)" "curl -LsSf https://astral.sh/uv/$UV_VERSION/install.sh | sh"
    have_uv=$(version_of uv)
    [ -n "$have_uv" ] || fail "user tools" "uv was installed but is not found" "open a new terminal and rerun"
    say "uv: installed $have_uv"
  fi
  if ok mise "$MISE_FLOOR"; then
    say "mise: present $have_mise (>= $MISE_FLOOR), left alone"
  else
    say "mise: installing $MISE_VERSION from https://mise.run"
    quiet mise env PATH="$orig_path" sh -c "curl -fsSL https://mise.run | MISE_VERSION=$MISE_VERSION sh" ||
      fail "user tools" "the mise installer failed (log above)" "curl -fsSL https://mise.run | MISE_VERSION=$MISE_VERSION sh"
    have_mise=$(version_of mise)
    [ -n "$have_mise" ] || fail "user tools" "mise was installed but is not found" "open a new terminal and rerun"
    say "mise: installed $have_mise"
  fi

  # --- 4. Agent: official native installers, current release -------------------------------
  for t in $agents; do
    if ok "$t" ""; then
      eval "say \"$t: present \${have_$t}, left alone\""
      continue
    fi
    case $t in
      claude)
        say "claude: installing the current Claude Code from https://claude.ai/install.sh"
        quiet claude env PATH="$orig_path" bash -c "curl -fsSL https://claude.ai/install.sh | bash" ||
          fail "agent" "the Claude Code installer failed (log above)" "curl -fsSL https://claude.ai/install.sh | bash"
        ;;
      codex)
        say "codex: installing the current Codex from https://chatgpt.com/codex/install.sh"
        quiet codex env PATH="$orig_path" sh -c "curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh" ||
          fail "agent" "the Codex installer failed (log above)" "curl -fsSL https://chatgpt.com/codex/install.sh | sh"
        ;;
    esac
    v=$(version_of "$t")
    [ -n "$v" ] || fail "agent" "$t was installed but is not found" "open a new terminal and rerun"
    eval "have_$t=\$v"
    say "$t: installed $v"
  done
  after=$(rc_state)
  if [ "$before" != "$after" ]; then
    say "PATH: the official installers changed $(rc_changes "$before" "$after"); open a new terminal to pick that up."
  fi
  case ":$orig_path:" in
    *":$HOME/.local/bin:"*) ;;
    *)
      if ! grep -qs '\.local/bin' "$HOME/.profile" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.zshrc" "$HOME/.zprofile" "$HOME/.zshenv" "$HOME/.config/fish/config.fish"; then
        say "PATH: ~/.local/bin is not on your PATH yet. Add it, then open a new terminal: echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.profile"
      fi
      ;;
  esac

  # --- 5. git identity ---------------------------------------------------------------------
  local name email
  name=$(git config --global user.name </dev/null)
  email=$(git config --global user.email </dev/null)
  if [ -n "$name" ] && [ -n "$email" ]; then
    say "git identity: already set, left alone"
  elif tty_ok; then
    while [ -z "$name" ]; do ask "[setup] Your name, for your git commits: "; name=$REPLY; done
    while [ -z "$email" ]; do ask "[setup] Your email, for your git commits: "; email=$REPLY; done
    if ! { git config --global user.name "$name" && git config --global user.email "$email"; }; then
      fail "git identity" "git config failed" "git config --global user.name \"Your Name\""
    fi
    say "git identity: set (git config --global user.name and user.email)"
  else
    say "git identity: not set, and there is no terminal to ask on. Set it with: git config --global user.name \"Your Name\"; git config --global user.email \"you@example.com\""
  fi

  # --- 6. Logins, in the browser ---------------------------------------------------------
  if [ -n "$no_login" ]; then
    say "logins: skipped (--no-login), so neither GitHub nor your agent is logged in by this run"
  else
    if gh auth status --hostname github.com >/dev/null 2>&1 </dev/null; then
      say "GitHub login: already logged in, left alone"
    else
      say "GitHub login: gh prints a one-time code, then opens your browser. Copy the code, then paste it there."
      gh auth login --hostname github.com --git-protocol https --web </dev/tty ||
        fail "GitHub login" "gh auth login did not finish" "gh auth login --hostname github.com --git-protocol https --web"
      say "GitHub login: done"
    fi
    gh auth setup-git --hostname github.com </dev/null >/dev/null 2>&1 ||
      fail "GitHub login" "gh auth setup-git failed" "gh auth setup-git --hostname github.com"
    say "git credential helper: gh (gh auth setup-git)"
    for t in $agents; do
      case $t in
        claude)
          if claude auth status >/dev/null 2>&1 </dev/null; then
            say "Claude Code login: already logged in, left alone"
          else
            say "Claude Code login: your browser opens; log in with your Claude account."
            claude auth login </dev/tty || fail "Claude Code login" "claude auth login did not finish" "claude auth login"
            say "Claude Code login: done"
          fi
          ;;
        codex)
          if codex login status >/dev/null 2>&1 </dev/null; then
            say "Codex login: already logged in, left alone"
          else
            say "Codex login: your browser opens; choose Sign in with ChatGPT."
            codex login </dev/tty || fail "Codex login" "codex login did not finish" "codex login (or codex login --device-auth)"
            say "Codex login: done"
          fi
          ;;
      esac
    done
  fi

  # --- 7. Clone ----------------------------------------------------------------------------
  if [ -n "$self_repo" ]; then
    say "clone: using the clone this script runs from, $clone (left as it is)"
  elif [ -e "$clone/.git" ]; then
    say "clone: $clone already exists, left as it is"
  else
    if [ -e "$clone" ] && [ -n "$(ls -A "$clone" 2>/dev/null)" ]; then
      fail "clone" "$clone exists, is not empty and is not a git clone" "rerun with --dir <another folder>"
    fi
    quiet clone git clone "$clone_url" "$clone" || fail "clone" "git clone failed (log above)" "git clone $clone_url $clone"
    say "clone: cloned $clone_url into $clone"
  fi
  if [ ! -f "$clone/setup/student/prepare.py" ]; then
    fail "clone" "$clone has no setup/student/prepare.py: it predates this setup" "cd $clone && git pull, then rerun"
  fi

  # --- 8 and 9. Prepare the repository, then the setup check (shared with install.ps1) -----
  if [ -n "$no_login" ]; then
    say "setup check: skipped (--no-login)"
    uv run --no-project --python 3.12 python "$clone/setup/student/prepare.py" --repo "$clone" --no-check </dev/null || exit 1
  else
    uv run --no-project --python 3.12 python "$clone/setup/student/prepare.py" --repo "$clone" </dev/null || exit 1
  fi
  say "Done: the course is in $clone."
}

main "$@"
