#!/usr/bin/env bash
# Install a pinned PowerShell 7 for running Session 1's test suite on Linux.
#
# sessions/01-fundamentals/tests/test_prework.py runs the student-facing
# check-setup.ps1 under PowerShell, so the suite needs a PowerShell host. This
# script downloads the official Linux tarball of the version pinned below,
# verifies its SHA-256, unpacks it under
#   ~/.local/share/coding-agent-cursus/pwsh/<version>/
# and links it as ~/.local/bin/pwsh. Nothing else is touched: no package
# manager, no sudo, no shell profile. If a PowerShell 7 or newer is already on
# PATH, or already linked at ~/.local/bin/pwsh, it is left alone. Safe to repeat.
#
#   bash setup/pwsh.sh
#
# Remove with: rm -rf ~/.local/share/coding-agent-cursus/pwsh ~/.local/bin/pwsh
set -euo pipefail

version=7.6.6
# From the release's hashes.sha256 and the GitHub release asset digests,
# https://github.com/PowerShell/PowerShell/releases/tag/v7.6.6 (checked 2026-10-10).
sha256_x64=ddbc4a2d113bbd46d283cfedcbcd117a70caefd7673f41f2b4e0000badf103bc
sha256_arm64=924829e54c983648f6f1419a2dc7f9433c861b2fb5bd57736ff096c24f133729

say() { echo "[pwsh] $*"; }
die() {
  echo "[pwsh] $*" >&2
  exit 1
}

# Prints the major version of a PowerShell executable, or nothing if it does not run.
major_of() {
  # shellcheck disable=SC2016 # $PSVersionTable is PowerShell's, not the shell's.
  "$1" -NoLogo -NoProfile -NonInteractive -Command '$PSVersionTable.PSVersion.Major' 2>/dev/null | tr -d '\r' || true
}

usable() {
  local major
  major=$(major_of "$1")
  [[ $major =~ ^[0-9]+$ ]] && [ "$major" -ge 7 ]
}

bin_dir="$HOME/.local/bin"
link="$bin_dir/pwsh"

if found=$(command -v pwsh 2>/dev/null) && usable "$found"; then
  say "PowerShell $(major_of "$found") already on PATH at $found; nothing to do."
  exit 0
fi
if [ -x "$link" ] && usable "$link"; then
  say "PowerShell already linked at $link; nothing to do."
  say "If 'pwsh' is not found, add $bin_dir to PATH."
  exit 0
fi

[ "$(uname -s)" = Linux ] || die "This script installs PowerShell on Linux only. On macOS or Windows, install PowerShell 7 from https://learn.microsoft.com/powershell/scripting/install/installing-powershell"
case $(uname -m) in
  x86_64 | amd64) arch=x64 sha256=$sha256_x64 ;;
  aarch64 | arm64) arch=arm64 sha256=$sha256_arm64 ;;
  *) die "Unsupported CPU architecture: $(uname -m)" ;;
esac
command -v curl >/dev/null 2>&1 || die "curl is required."
command -v tar >/dev/null 2>&1 || die "tar is required."
if command -v sha256sum >/dev/null 2>&1; then
  hash_of() { sha256sum "$1" | cut -d' ' -f1; }
elif command -v shasum >/dev/null 2>&1; then
  hash_of() { shasum -a 256 "$1" | cut -d' ' -f1; }
else
  die "sha256sum or shasum is required."
fi

asset="powershell-$version-linux-$arch.tar.gz"
url="https://github.com/PowerShell/PowerShell/releases/download/v$version/$asset"
dest="$HOME/.local/share/coding-agent-cursus/pwsh/$version"

if ! { [ -x "$dest/pwsh" ] && usable "$dest/pwsh"; }; then
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  say "Downloading $asset"
  curl -fsSL --retry 3 -o "$tmp/$asset" "$url" || die "Download failed: $url"
  actual=$(hash_of "$tmp/$asset")
  [ "$actual" = "$sha256" ] || die "SHA-256 mismatch for $asset: expected $sha256, got $actual. Nothing installed."
  mkdir -p "$tmp/unpacked"
  tar -xzf "$tmp/$asset" -C "$tmp/unpacked"
  chmod +x "$tmp/unpacked/pwsh"
  rm -rf "$dest"
  mkdir -p "$(dirname "$dest")"
  mv "$tmp/unpacked" "$dest"
fi

if ! usable "$dest/pwsh"; then
  die "PowerShell $version is unpacked at $dest but does not start. It needs the ICU library: install your distribution's libicu package (for example 'sudo apt-get install libicu-dev' or 'sudo dnf install libicu'), or set DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 when running pwsh."
fi

mkdir -p "$bin_dir"
ln -sfn "$dest/pwsh" "$link"
say "PowerShell $version installed at $dest and linked as $link."
case ":$PATH:" in
  *":$bin_dir:"*) ;;
  *) say "Add $bin_dir to PATH (or set CURSUS_PWSH=$link) so the tests can find it." ;;
esac
