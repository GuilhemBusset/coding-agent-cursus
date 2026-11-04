# CI (student-setup.yml): run the Windows student setup twice, non-interactively, then check it.
#
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File run_twice.ps1 -Source <checkout>
#
# Each run goes through iex, as `irm <url> | iex` does, in a new Windows PowerShell 5.1
# process: the script text comes from the checkout under test instead of main, and the options
# are the environment variables the one-liner relies on (CURSUS_YES, CURSUS_AGENT,
# CURSUS_NO_LOGIN). Then ci_verify.py checks the tools, hooks, session sync, the rerun and the
# clone's state. ASCII and PowerShell 5.1 syntax only.

param([Parameter(Mandatory = $true)][string]$Source)

# Exit codes are checked one by one: native stderr must not stop the script.
$ErrorActionPreference = 'Continue'
$Source = (Resolve-Path $Source).Path
$clone = Join-Path $env:USERPROFILE 'coding-agent-cursus'
$logs = Join-Path $env:USERPROFILE 'student-setup-logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$env:CURSUS_YES = '1'
$env:CURSUS_AGENT = 'both'
$env:CURSUS_NO_LOGIN = '1'
$env:CURSUS_RAW_BASE = $Source
$env:CURSUS_CLONE_URL = $Source
$script = Join-Path $Source 'setup\student\install.ps1'
$verify = Join-Path $Source 'tests\student_setup\ci_verify.py'
Write-Output "Running the setup with Windows PowerShell $($PSVersionTable.PSVersion)"

function Find-Uv {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machine, $user, $env:Path) | Where-Object { $_ }) -join ';'
    return (Get-Command uv -CommandType Application | Select-Object -First 1).Source
}

foreach ($run in @('first', 'second')) {
    Write-Output "::group::$run run"
    $log = Join-Path $logs "$run.log"
    $command = "Get-Content -Raw -Path '$script' | Invoke-Expression; exit `$LASTEXITCODE"
    # Shown as it runs, and kept as UTF-8 (Tee-Object would write UTF-16 in Windows PowerShell 5.1).
    $lines = New-Object System.Collections.Generic.List[string]
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -Command $command 2>&1 | ForEach-Object {
        $text = [string]$_
        Write-Output $text
        $lines.Add($text)
    }
    $status = $LASTEXITCODE
    [System.IO.File]::WriteAllLines($log, $lines)
    Write-Output '::endgroup::'
    if ($status -ne 0) { throw "The $run run failed (exit $status)." }
    if ($run -eq 'first') {
        & (Find-Uv) run --no-project --python 3.12 python $verify --clone $clone --record (Join-Path $logs 'state.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Could not record the clone state.' }
    }
}

& (Find-Uv) run --no-project --python 3.12 python $verify --clone $clone --first (Join-Path $logs 'first.log') `
    --second (Join-Path $logs 'second.log') --before (Join-Path $logs 'state.txt') --agents 'claude,codex' --preinstalled 'git,gh'
if ($LASTEXITCODE -ne 0) { throw 'ci_verify.py found a problem (see above).' }
