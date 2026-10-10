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
# It calls .NET directly rather than cmdlets such as Get-Command, which would load
# PowerShell modules and slow every run down.

$ErrorActionPreference = 'Continue'
$checker = [System.IO.Path]::Combine($PSScriptRoot, 'check_setup.py')
$onWindows = [System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT

function Write-Line([string]$Text) {
    [Console]::Out.WriteLine($Text)
}

Write-Line 'Checking your setup for Session 1. The agent smoke test can take a minute or two.'

# The first program called $Name on PATH (with a PATHEXT extension on Windows), or $null.
function Find-Tool([string]$Name) {
    $extensions = @('')
    if ($onWindows) {
        $extensions = @($env:PATHEXT -split ';' | Where-Object { $_ })
        if ($extensions.Count -eq 0) { $extensions = @('.COM', '.EXE', '.BAT', '.CMD') }
    }
    foreach ($dir in ($env:PATH -split [System.IO.Path]::PathSeparator)) {
        if (-not $dir) { continue }
        foreach ($extension in $extensions) {
            $candidate = [System.IO.Path]::Combine($dir, $Name + $extension)
            if ([System.IO.File]::Exists($candidate)) { return $candidate }
        }
    }
    return $null
}

function Get-OsName {
    if ($onWindows) {
        return 'Windows'
    }
    if ([System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::OSX)) {
        return 'macOS'
    }
    $wsl = $false
    if ($env:WSL_DISTRO_NAME) {
        $wsl = $true
    } elseif ([System.IO.File]::Exists('/proc/version')) {
        if ([System.IO.File]::ReadAllText('/proc/version') -match 'microsoft') { $wsl = $true }
    }
    if ($wsl) { return 'Linux (WSL)' }
    return 'Linux'
}

# Presence-only report for when the Python checker could not run at all.
function Write-Fallback([string]$First) {
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add($First)
    foreach ($name in @('git', 'gh', 'mise')) {
        if (Find-Tool $name) {
            $lines.Add("${name}: PASS found (version not checked)")
        } else {
            $lines.Add("${name}: FAIL not found on PATH; see 'Install the tools' on the pre-work page")
        }
    }
    $agents = @()
    foreach ($name in @('claude', 'codex')) {
        if (Find-Tool $name) {
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
    $failures = 0
    foreach ($line in $lines) {
        Write-Line $line
        if ($line -like '*: FAIL*') { $failures += 1 }
    }
    Write-Line '----- BEGIN SETUP SUMMARY -----'
    Write-Line ('date: ' + [DateTime]::UtcNow.ToString('yyyy-MM-dd') + ' (UTC)')
    Write-Line ('os: ' + (Get-OsName))
    Write-Line 'github: unknown'
    foreach ($line in $lines) { Write-Line $line }
    Write-Line "result: FAIL ($failures FAIL)"
    Write-Line '----- END SETUP SUMMARY -----'
}

$uv = Find-Tool 'uv'
if ($null -eq $uv) {
    Write-Fallback "uv: FAIL not found on PATH; install uv (see 'Install the tools' on the pre-work page), open a new terminal and rerun"
    exit 1
}

# uv's own messages (for example a first-time Python download) go to stderr and are
# not shown; the checker prints everything it reports on stdout.
& $uv run --no-project --python 3.12 python $checker 2>$null
$status = $LASTEXITCODE
if ($status -eq 0 -or $status -eq 1) {
    exit $status
}
Write-Fallback "checker: FAIL could not start the checker through uv (exit $status); run 'uv run --no-project --python 3.12 python --version' to see why"
exit 1
