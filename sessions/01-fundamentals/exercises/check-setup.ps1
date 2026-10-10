# Session 1 pre-work: check that this machine is ready for the session.
# Instructions: 00-prework.html in this folder, section "Check your setup".
#
# Windows PowerShell, from the root of your course clone:
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\sessions\01-fundamentals\exercises\check-setup.ps1
#
# or from this folder:
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\check-setup.ps1
#
# (In Git Bash, WSL, macOS or Linux, use check-setup.sh next to this file instead.)
#
# The checks live in check_setup.py next to this file, which runs with Python 3.12
# through uv. It prints PASS or FAIL for each tool, the network, your GitHub login, a
# push to a temporary branch setup-check/<your handle> (deleted straight after), and a
# smoke test of whichever agent you have, then a summary block to paste into the form
# your instructor gives you. It exits non-zero if anything FAILs. It never prints a
# secret. If uv is missing or cannot start the checker, this script still reports which
# tools it can find, prints the summary block and exits non-zero.
#
# Written for Windows PowerShell 5.1 as well as PowerShell 7: keep it ASCII and avoid
# 7-only syntax (pipeline chains, ternaries, null-coalescing operators, $IsWindows).

$ErrorActionPreference = 'Continue'
$checker = Join-Path $PSScriptRoot 'check_setup.py'

Write-Output 'Checking your setup for Session 1. The agent smoke test can take a minute or two.'

function Get-Tool([string]$Name) {
    return Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Get-OsName {
    if ([System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT) {
        return 'Windows'
    }
    if ([System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::OSX)) {
        return 'macOS'
    }
    $wsl = $false
    if ($env:WSL_DISTRO_NAME) {
        $wsl = $true
    } elseif (Test-Path '/proc/version') {
        if ((Get-Content '/proc/version' -Raw) -match 'microsoft') { $wsl = $true }
    }
    if ($wsl) { return 'Linux (WSL)' }
    return 'Linux'
}

# Presence-only report for when the Python checker could not run at all.
function Write-Fallback([string]$First) {
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add($First)
    foreach ($name in @('git', 'gh', 'mise')) {
        if (Get-Tool $name) {
            $lines.Add("${name}: PASS found (version not checked)")
        } else {
            $lines.Add("${name}: FAIL not found on PATH; see 'Install the tools' on the pre-work page")
        }
    }
    $agents = @()
    foreach ($name in @('claude', 'codex')) {
        if (Get-Tool $name) {
            $lines.Add("${name}: PASS found (not smoke-tested)")
            $agents += $name
        } else {
            $lines.Add("${name}: not installed (fine)")
        }
    }
    if ($agents.Count -gt 0) {
        $lines.Add('agent: PASS found ' + ($agents -join ' and '))
    } else {
        $lines.Add('agent: FAIL neither Claude Code nor Codex is installed')
    }
    foreach ($line in $lines) { Write-Output $line }
    $failures = @($lines | Where-Object { $_ -like '*: FAIL*' }).Count
    Write-Output '----- BEGIN SETUP SUMMARY -----'
    Write-Output ('date: ' + [DateTime]::UtcNow.ToString('yyyy-MM-dd') + ' (UTC)')
    Write-Output ('os: ' + (Get-OsName))
    Write-Output 'github: unknown'
    foreach ($line in $lines) { Write-Output $line }
    Write-Output "result: FAIL ($failures FAIL)"
    Write-Output '----- END SETUP SUMMARY -----'
}

$uv = Get-Tool 'uv'
if ($null -eq $uv) {
    Write-Fallback "uv: FAIL not found on PATH; install uv (see 'Install the tools' on the pre-work page), open a new terminal and rerun"
    exit 1
}

# uv's own messages (for example a first-time Python download) go to stderr and are
# not shown; the checker prints everything it reports on stdout.
& $uv.Path run --no-project --python 3.12 python $checker 2>$null
$status = $LASTEXITCODE
if ($status -eq 0 -or $status -eq 1) {
    exit $status
}
Write-Fallback "checker: FAIL could not start the checker through uv (exit $status); run 'uv run --no-project --python 3.12 python --version' to see why"
exit 1
