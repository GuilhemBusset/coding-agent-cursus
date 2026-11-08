# Student setup for Windows (PowerShell): from a fresh machine to a ready course clone.
# Instructions: setup/student/README.md. On macOS, Linux or WSL, use install.sh instead.
#
#   irm https://raw.githubusercontent.com/GuilhemBusset/coding-agent-cursus/main/setup/student/install.ps1 | iex
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\setup\student\install.ps1 [options]   # from a clone
#
# It shows a plan and asks once, then installs what is missing: git (Git for Windows, which
# includes Git Bash) and gh through winget, uv and mise through their official installers at the
# versions pinned in versions.env, and Claude Code, Codex or both through their official native
# installers. Then it sets your git identity, logs you in to GitHub and to your agent in the
# browser, clones the course (or reuses this clone), and runs prepare.py: git hooks, every
# session synced from its lockfile, and the setup check. A tool already at or above its floor is
# left alone. Rerunning it is safe: it skips what is done. No step needs an administrator
# PowerShell; Git for Windows' installer asks for approval (UAC) itself.
#
# Options. `irm ... | iex` cannot pass any, so each one is also an environment variable:
#   -Yes          $env:CURSUS_YES = '1'        do not ask to confirm the plan
#   -Agent A      $env:CURSUS_AGENT = 'A'      claude, codex or both (otherwise it asks)
#   -NoLogin      $env:CURSUS_NO_LOGIN = '1'   skip the logins and the setup check (step 6 and 9)
#   -DryRun       $env:CURSUS_DRY_RUN = '1'    print the plan and change nothing
#   -Dir DIR      $env:CURSUS_DIR = 'DIR'      where to clone (default ~\coding-agent-cursus)
#
# A download can fail for a moment (a 504 from GitHub, a dropped connection): each official
# installer, and each sync step of prepare.py, is tried again after 10, 30 and 60 seconds before
# the step fails. The tests shorten that with CURSUS_RETRY_DELAYS (whole seconds, space-separated).
#
# Written for Windows PowerShell 5.1, the version Windows ships: keep it ASCII and avoid
# 7-only syntax (pipeline chains, ternaries, null-coalescing operators, $IsWindows). Run
# through iex it never calls `exit`, which would close the window; it sets $LASTEXITCODE.

param(
    [switch]$Yes,
    [string]$Agent = '',
    [switch]$NoLogin,
    [switch]$DryRun,
    [string]$Dir = ''
)

function Invoke-CursusSetup([hashtable]$State) {
    $ErrorActionPreference = 'Continue'
    $ProgressPreference = 'SilentlyContinue'

    function Write-Line([string]$Text) { [Console]::Out.WriteLine($Text) }
    function Say([string]$Text) { Write-Line ('[setup] ' + $Text) }
    function Stop-Setup([string]$Step, [string]$Why, [string]$Next) {
        Say "FAILED at ${Step}: $Why"
        if ($Next) { Say "Next: $Next" }
        Say 'Then rerun the same command; it continues from there.'
        throw 'cursus-setup-stopped'
    }
    function Test-Truthy([string]$Value) { return ($Value -match '^(?i:1|true|yes|y)$') }
    function Find-Tool([string]$Name) {
        $found = Get-Command -Name $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { return $found.Source }
        return $null
    }
    # The first X.Y.Z (or X.Y) in a tool's --version output, or '' if it does not run.
    function Get-ToolVersion([string]$Name) {
        $path = Find-Tool $Name
        if (-not $path) { return '' }
        try { $out = @(& $path --version 2>$null) } catch { return '' }
        if ($out.Count -eq 0) { return '' }
        if ([string]$out[0] -match '(\d+)\.(\d+)(?:\.(\d+))?') {
            $patch = '0'
            if ($Matches[3]) { $patch = $Matches[3] }
            return ($Matches[1] + '.' + $Matches[2] + '.' + $patch)
        }
        return ''
    }
    function Test-Floor([string]$Version, [string]$Floor) {
        if (-not $Version) { return $false }
        if (-not $Floor) { return $true }
        return ([version]$Version -ge [version]$Floor)
    }
    function Test-Terminal { return (-not [Console]::IsInputRedirected) }
    function Get-UserPath { return [Environment]::GetEnvironmentVariable('Path', 'User') }
    # After each install: this window's Path from the registry, so later steps find the tool.
    function Update-SessionPath {
        $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $user = Get-UserPath
        if ($null -eq $machine -and $null -eq $user) { return }
        $parts = New-Object System.Collections.Generic.List[string]
        foreach ($entry in ((@($machine, $user, $env:Path) | Where-Object { $_ }) -join ';').Split(';')) {
            if ($entry -and -not $parts.Contains($entry)) { $parts.Add($entry) }
        }
        $env:Path = $parts -join ';'
    }
    # Runs a program with its output in a log; on failure, shows the end of it. Returns the exit code.
    function Invoke-Logged([string]$Name, [string]$Exe, [string[]]$Arguments) {
        $log = Join-Path $State.Work ($Name + '.log')
        $global:LASTEXITCODE = 0
        & $Exe @Arguments 2>&1 | ForEach-Object { [string]$_ } | Set-Content -Path $log -Encoding UTF8
        $code = $LASTEXITCODE
        if ($code -ne 0 -and (Test-Path $log)) {
            foreach ($line in @(Get-Content -Path $log -Tail 15)) { Write-Line ('  | ' + $line) }
        }
        return $code
    }
    function Invoke-Installer([string]$Name, [string]$Command) {
        $shell = (Get-Process -Id $PID).Path
        return (Invoke-Logged $Name $shell @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $Command))
    }
    function Write-PathChange([string]$Before, [string]$Tool) {
        $after = Get-UserPath
        if ($null -eq $after -or $after -eq $Before) { return }
        $old = @(([string]$Before).Split(';'))
        $added = @($after.Split(';') | Where-Object { $_ -and ($old -notcontains $_) })
        if ($added.Count -gt 0) { Say ("PATH: $Tool's installer added to your user Path: " + ($added -join '; ')) }
    }

    # --- Options ---------------------------------------------------------------------------
    $yes = $State.Yes -or (Test-Truthy $env:CURSUS_YES)
    $noLogin = $State.NoLogin -or (Test-Truthy $env:CURSUS_NO_LOGIN)
    $dryRun = $State.DryRun -or (Test-Truthy $env:CURSUS_DRY_RUN)
    $agent = $State.Agent
    if (-not $agent) { $agent = [string]$env:CURSUS_AGENT }
    $dir = $State.Dir
    if (-not $dir) { $dir = [string]$env:CURSUS_DIR }
    if (@('', 'claude', 'codex', 'both') -notcontains $agent) {
        Stop-Setup 'options' "-Agent must be claude, codex or both, not '$agent'" 'rerun with CURSUS_AGENT set to claude, codex or both'
    }
    # Seconds to wait before each new attempt of a failed installer (prepare.py reads the same).
    $delays = @(10, 30, 60)
    if ($env:CURSUS_RETRY_DELAYS) {
        $delays = @()
        foreach ($d in @($env:CURSUS_RETRY_DELAYS -split '\s+' | Where-Object { $_ })) {
            if ($d -notmatch '^\d+$') {
                Stop-Setup 'options' "CURSUS_RETRY_DELAYS must be whole seconds separated by spaces, not '$($env:CURSUS_RETRY_DELAYS)'" 'Remove-Item Env:CURSUS_RETRY_DELAYS'
            }
            $delays += [int]$d
        }
    }
    $repoSlug = 'GuilhemBusset/coding-agent-cursus'
    if ($env:CURSUS_REPO) { $repoSlug = $env:CURSUS_REPO }
    $rawBase = "https://raw.githubusercontent.com/$repoSlug/main"
    if ($env:CURSUS_RAW_BASE) { $rawBase = $env:CURSUS_RAW_BASE }
    $cloneUrl = "https://github.com/$repoSlug.git"
    if ($env:CURSUS_CLONE_URL) { $cloneUrl = $env:CURSUS_CLONE_URL }
    $userHome = $env:USERPROFILE
    if (-not $userHome) { $userHome = $HOME }

    if ($env:OS -ne 'Windows_NT') {
        Stop-Setup 'plan' 'install.ps1 is for Windows' 'on macOS, Linux or WSL, run install.sh (see setup/student/README.md)'
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    $selfDir = $State.ScriptRoot
    $selfRepo = ''
    if ($selfDir -and (Test-Path (Join-Path $selfDir 'prepare.py')) -and (Test-Path (Join-Path $selfDir '..\..\.git'))) {
        $selfRepo = (Resolve-Path (Join-Path $selfDir '..\..')).Path
    }

    # --- Pins and floors -------------------------------------------------------------------
    if ($selfDir -and (Test-Path (Join-Path $selfDir 'versions.env'))) {
        $versions = [System.IO.File]::ReadAllText((Join-Path $selfDir 'versions.env'))
    } elseif ($rawBase -notmatch '^https?://') {
        # A local checkout (CI runs the script through iex from one, as the one-liner would).
        $base = $rawBase
        if ($base -match '^file:') { $base = ([Uri]$base).LocalPath }
        $local = Join-Path $base 'setup\student\versions.env'
        if (-not (Test-Path $local)) { Stop-Setup 'plan' "no versions.env at $local" 'check CURSUS_RAW_BASE' }
        $versions = [System.IO.File]::ReadAllText($local)
    } else {
        try { $versions = [string](Invoke-RestMethod -Uri "$rawBase/setup/student/versions.env" -UseBasicParsing) }
        catch { Stop-Setup 'plan' "could not download $rawBase/setup/student/versions.env" 'check your network connection' }
    }
    $pin = @{}
    foreach ($line in ($versions -split "`r?`n")) {
        if ($line -match '^([A-Z0-9_]+)=(.*)$') { $pin[$Matches[1]] = $Matches[2].Trim() }
    }
    foreach ($key in @('UV_VERSION', 'MISE_VERSION', 'GIT_FLOOR', 'GH_FLOOR', 'UV_FLOOR', 'MISE_FLOOR')) {
        if (-not $pin[$key]) { Stop-Setup 'plan' "versions.env has no $key" 'report this to your instructor' }
    }
    $floor = @{ git = $pin.GIT_FLOOR; gh = $pin.GH_FLOOR; uv = $pin.UV_FLOOR; mise = $pin.MISE_FLOOR; claude = ''; codex = '' }

    # --- 1. Plan -----------------------------------------------------------------------------
    $build = [Environment]::OSVersion.Version.Build
    $windows = 'Windows 10'
    if ($build -ge 22000) { $windows = 'Windows 11' }
    $arch = $env:PROCESSOR_ARCHITECTURE
    Say "Course setup for the Windows (PowerShell) track ($windows build $build, $arch; PowerShell $($PSVersionTable.PSVersion))."
    $have = @{}
    foreach ($tool in @('git', 'gh', 'uv', 'mise', 'claude', 'codex')) { $have[$tool] = Get-ToolVersion $tool }
    $winget = Find-Tool 'winget'

    $agents = @()
    if ($agent -eq 'claude') { $agents = @('claude') }
    if ($agent -eq 'codex') { $agents = @('codex') }
    if ($agent -eq 'both') { $agents = @('claude', 'codex') }
    if (-not $agent -and -not $dryRun) {
        if (-not (Test-Terminal)) {
            Stop-Setup 'agent' 'no terminal to ask which agent to install' "set `$env:CURSUS_AGENT = 'claude' (or 'codex', or 'both') and rerun"
        }
        while ($agents.Count -eq 0) {
            $reply = Read-Host '[setup] Which agent do you use? 1) Claude Code  2) Codex  3) both [1/2/3]'
            if ($reply -eq '1' -or $reply -eq 'claude') { $agent = 'claude'; $agents = @('claude') }
            if ($reply -eq '2' -or $reply -eq 'codex') { $agent = 'codex'; $agents = @('codex') }
            if ($reply -eq '3' -or $reply -eq 'both') { $agent = 'both'; $agents = @('claude', 'codex') }
        }
    }
    if ($agents.Count -eq 0) { $agents = @('claude', 'codex') }

    $how = @{
        git    = 'Git for Windows (includes Git Bash) with winget install --id Git.Git -e --source winget --scope user, into ~\AppData\Local\Programs\Git'
        gh     = 'GitHub CLI with winget install --id GitHub.cli -e --source winget --scope user, into ~\AppData\Local\Microsoft\WinGet'
        uv     = "uv $($pin.UV_VERSION) from https://astral.sh/uv/$($pin.UV_VERSION)/install.ps1, into ~\.local\bin"
        mise   = "mise $($pin.MISE_VERSION) from https://mise.run/powershell, into ~\.local\bin"
        claude = 'the current Claude Code from https://claude.ai/install.ps1, into ~\.local\bin'
        codex  = 'the current Codex from https://chatgpt.com/codex/install.ps1, into ~\AppData\Local\Programs\OpenAI\Codex\bin'
    }
    $cloneHow = ''
    if ($selfRepo) {
        $clone = $selfRepo
        $cloneHow = 'reuse the clone this script runs from, as it is'
    } else {
        $clone = $dir
        if (-not $clone) { $clone = Join-Path $userHome 'coding-agent-cursus' }
        $clone = [System.IO.Path]::GetFullPath($clone)
        if (Test-Path (Join-Path $clone '.git')) { $cloneHow = 'reuse the existing clone, as it is' } else { $cloneHow = "git clone $cloneUrl" }
    }

    Say 'Plan (nothing has changed yet):'
    foreach ($tool in (@('git', 'gh', 'uv', 'mise') + $agents)) {
        $v = $have[$tool]
        $label = $tool.PadRight(8)
        if (Test-Floor $v $floor[$tool]) {
            $suffix = ''
            if ($floor[$tool]) { $suffix = " (>= $($floor[$tool]))" }
            Write-Line "  $label present $v$suffix, left alone"
        } elseif ($v) {
            Write-Line "  $label present $v, below the floor $($floor[$tool]): install $($how[$tool])"
        } else {
            Write-Line "  $label missing: install $($how[$tool])"
        }
    }
    if (-not $agent) { Write-Line '           (it asks which agent you use: Claude Code, Codex or both)' }
    if ($yes -and $noLogin) {
        Write-Line '  identity your git user.name and user.email: not asked for (-Yes -NoLogin)'
    } else {
        Write-Line '  identity your git user.name and user.email: asked for if not set'
    }
    if ($noLogin) {
        Write-Line '  logins   skipped (-NoLogin), and so is the setup check'
    } else {
        Write-Line '  logins   GitHub (gh auth login) then your agent, in the browser, if not logged in yet'
    }
    Write-Line "  clone    ${clone}: $cloneHow"
    Write-Line '  prepare  git hooks, then mise trust, mise install, mise exec -- uv sync --locked in every session'
    if (-not $noLogin) { Write-Line "  check    the latest session's setup check, with its summary block" }
    $needGit = -not (Test-Floor $have.git $floor.git)
    $needGh = -not (Test-Floor $have.gh $floor.gh)
    if ($needGit) {
        Say 'Git for Windows: its installer asks for administrator approval (UAC) even for a per-user install. Approve it.'
        Write-Line '  If you decline, the setup stops; install Git from https://git-scm.com/install/windows instead, then rerun.'
    }
    if ($needGh) { Say 'GitHub CLI: winget may ask for administrator approval (UAC) if it picks the MSI installer.' }
    if (($needGit -or $needGh) -and -not $winget) {
        Say 'winget (App Installer) is missing: this setup stops at the system tools step without it.'
    }
    if (Test-Path Env:ANTHROPIC_API_KEY) {
        Say "Note: ANTHROPIC_API_KEY is set (value hidden). Claude Code uses it instead of your subscription; see 'Login troubleshooting' on the pre-work page."
    }

    if ($dryRun) {
        Say 'Dry run: nothing was installed, written or changed.'
        return
    }
    if (-not (Test-Terminal) -and -not ($yes -and $noLogin)) {
        Stop-Setup 'plan' 'no terminal to ask on (the logins need one)' 'run it in a PowerShell window, or non-interactively with CURSUS_YES=1, CURSUS_AGENT and CURSUS_NO_LOGIN=1'
    }
    if (-not $yes) {
        $reply = Read-Host '[setup] Go ahead? [Y/n]'
        if (@('', 'y', 'Y', 'yes', 'Yes') -notcontains $reply) { Say 'Stopped: nothing was changed.'; return }
    }
    $State.Work = Join-Path ([System.IO.Path]::GetTempPath()) ('cursus-setup-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $State.Work -Force | Out-Null

    # --- 2. System tools: winget ---------------------------------------------------------------
    $wingetArgs = @('-e', '--source', 'winget', '--scope', 'user', '--silent', '--accept-package-agreements', '--accept-source-agreements')
    foreach ($tool in @('git', 'gh')) {
        if (Test-Floor $have[$tool] $floor[$tool]) {
            Say "${tool}: present $($have[$tool]) (>= $($floor[$tool])), left alone"
            continue
        }
        if (-not $winget) {
            Stop-Setup 'system tools' "$tool is missing and winget (App Installer) is not available" 'install App Installer from the Microsoft Store, or follow the Windows commands under Install the tools on the pre-work page'
        }
        $id = 'Git.Git'
        if ($tool -eq 'gh') { $id = 'GitHub.cli' }
        Say "${tool}: installing $id with winget"
        $before = Get-UserPath
        $code = Invoke-Logged $tool $winget (@('install', '--id', $id) + $wingetArgs)
        Update-SessionPath
        $have[$tool] = Get-ToolVersion $tool
        if ($code -ne 0 -and -not $have[$tool]) {
            if ($tool -eq 'git') {
                Stop-Setup 'system tools' "winget could not install Git for Windows (exit $code). If you declined the administrator prompt (UAC), nothing was installed" 'rerun and approve the prompt, or install Git from https://git-scm.com/install/windows'
            }
            Stop-Setup 'system tools' "winget could not install the GitHub CLI (exit $code)" 'winget install --id GitHub.cli -e --source winget'
        }
        if (-not $have[$tool]) { Stop-Setup 'system tools' "$tool was installed but is not found" 'open a new PowerShell window and rerun' }
        if (-not (Test-Floor $have[$tool] $floor[$tool])) {
            Stop-Setup 'system tools' "$tool $($have[$tool]) at $(Find-Tool $tool) is still below the floor $($floor[$tool]) after installing it" "remove the older $tool, or run winget upgrade --id $id -e --source winget, then rerun"
        }
        Write-PathChange $before $id
        Say "${tool}: installed $($have[$tool])"
    }

    # --- 3 and 4. uv, mise and the agent: official installers ------------------------------
    $installers = @{
        uv     = "irm https://astral.sh/uv/$($pin.UV_VERSION)/install.ps1 | iex"
        mise   = 'irm https://mise.run/powershell | iex'
        claude = 'irm https://claude.ai/install.ps1 | iex'
        codex  = 'irm https://chatgpt.com/codex/install.ps1 | iex'
    }
    $steps = @{ uv = 'user tools'; mise = 'user tools'; claude = 'agent'; codex = 'agent' }
    $oldMise = $env:MISE_VERSION
    $oldCodex = $env:CODEX_NON_INTERACTIVE
    $env:MISE_VERSION = $pin.MISE_VERSION
    $env:CODEX_NON_INTERACTIVE = '1'
    try {
        foreach ($tool in (@('uv', 'mise') + $agents)) {
            if (Test-Floor $have[$tool] $floor[$tool]) {
                $suffix = ''
                if ($floor[$tool]) { $suffix = " (>= $($floor[$tool]))" }
                Say "${tool}: present $($have[$tool])$suffix, left alone"
                continue
            }
            Say "${tool}: installing $($how[$tool].Split(',')[0])"
            $before = Get-UserPath
            $attempt = 1
            while ($true) {
                $code = Invoke-Installer $tool $installers[$tool]
                Update-SessionPath
                $have[$tool] = Get-ToolVersion $tool
                if ($tool -eq 'claude' -and -not $have[$tool]) {
                    # Claude Code's launcher is ~\.local\bin\claude.exe; put that folder on the user Path if needed.
                    $bin = Join-Path $userHome '.local\bin'
                    $user = Get-UserPath
                    if ((Test-Path (Join-Path $bin 'claude.exe')) -and (@(([string]$user).Split(';')) -notcontains $bin)) {
                        [Environment]::SetEnvironmentVariable('Path', ((@($user, $bin) | Where-Object { $_ }) -join ';'), 'User')
                        Update-SessionPath
                        $have[$tool] = Get-ToolVersion $tool
                    }
                }
                # A download can fail for a moment, so a failed attempt is tried again. Failed means a
                # nonzero exit, or no tool at the floor afterwards: iex can hide a native command's
                # exit code. Rerunning an installer is safe.
                if (($code -eq 0 -and (Test-Floor $have[$tool] $floor[$tool])) -or $attempt -gt $delays.Count) { break }
                $wait = $delays[$attempt - 1]
                Say "${tool}: the installer did not finish (exit $code; attempt $attempt of $($delays.Count + 1)); trying again in $wait s"
                Start-Sleep -Seconds $wait
                $attempt++
            }
            if ($code -ne 0 -or -not $have[$tool]) {
                Stop-Setup $steps[$tool] "the $tool installer did not finish (exit $code; log above)" $installers[$tool]
            }
            if (-not (Test-Floor $have[$tool] $floor[$tool])) {
                Stop-Setup $steps[$tool] "$tool $($have[$tool]) at $(Find-Tool $tool) is still below the floor $($floor[$tool]) after installing it" "remove that older $tool, open a new PowerShell window and rerun"
            }
            Write-PathChange $before $tool
            Say "${tool}: installed $($have[$tool])"
        }
    } finally {
        $env:MISE_VERSION = $oldMise
        $env:CODEX_NON_INTERACTIVE = $oldCodex
    }

    # --- 5. git identity ---------------------------------------------------------------------
    $git = Find-Tool 'git'
    $name = [string](& $git config --global user.name)
    $email = [string](& $git config --global user.email)
    if ($name -and $email) {
        Say 'git identity: already set, left alone'
    } elseif ($yes -and $noLogin) {
        # -Yes with -NoLogin runs without a single prompt, terminal or not.
        Say 'git identity: not set, and not asked for (-Yes -NoLogin). Set it with: git config --global user.name "Your Name"; git config --global user.email "you@example.com"'
    } elseif (Test-Terminal) {
        while (-not $name) { $name = Read-Host '[setup] Your name, for your git commits' }
        while (-not $email) { $email = Read-Host '[setup] Your email, for your git commits' }
        & $git config --global user.name $name
        & $git config --global user.email $email
        Say 'git identity: set (git config --global user.name and user.email)'
    } else {
        Say 'git identity: not set, and there is no terminal to ask on. Set it with: git config --global user.name "Your Name"; git config --global user.email "you@example.com"'
    }

    # --- 6. Logins, in the browser -----------------------------------------------------------
    if ($noLogin) {
        Say 'logins: skipped (-NoLogin), so neither GitHub nor your agent is logged in by this run'
    } else {
        $gh = Find-Tool 'gh'
        & $gh auth status --hostname github.com *> $null
        if ($LASTEXITCODE -eq 0) {
            Say 'GitHub login: already logged in, left alone'
        } else {
            Say 'GitHub login: gh prints a one-time code, then opens your browser. Copy the code, then paste it there.'
            & $gh auth login --hostname github.com --git-protocol https --web
            if ($LASTEXITCODE -ne 0) { Stop-Setup 'GitHub login' 'gh auth login did not finish' 'gh auth login --hostname github.com --git-protocol https --web' }
            Say 'GitHub login: done'
        }
        & $gh auth setup-git --hostname github.com *> $null
        if ($LASTEXITCODE -ne 0) { Stop-Setup 'GitHub login' 'gh auth setup-git failed' 'gh auth setup-git --hostname github.com' }
        Say 'git credential helper: gh (gh auth setup-git)'
        foreach ($tool in $agents) {
            $exe = Find-Tool $tool
            if ($tool -eq 'claude') {
                & $exe auth status *> $null
                if ($LASTEXITCODE -eq 0) { Say 'Claude Code login: already logged in, left alone'; continue }
                Say 'Claude Code login: your browser opens; log in with your Claude account.'
                & $exe auth login
                if ($LASTEXITCODE -ne 0) { Stop-Setup 'Claude Code login' 'claude auth login did not finish' 'claude auth login' }
                Say 'Claude Code login: done'
            } else {
                & $exe login status *> $null
                if ($LASTEXITCODE -eq 0) { Say 'Codex login: already logged in, left alone'; continue }
                Say 'Codex login: your browser opens; choose Sign in with ChatGPT.'
                & $exe login
                if ($LASTEXITCODE -ne 0) { Stop-Setup 'Codex login' 'codex login did not finish' 'codex login (or codex login --device-auth)' }
                Say 'Codex login: done'
            }
        }
    }

    # --- 7. Clone ----------------------------------------------------------------------------
    if ($selfRepo) {
        Say "clone: using the clone this script runs from, $clone (left as it is)"
    } elseif (Test-Path (Join-Path $clone '.git')) {
        Say "clone: $clone already exists, left as it is"
    } else {
        if ((Test-Path $clone) -and @(Get-ChildItem -Force -Path $clone).Count -gt 0) {
            Stop-Setup 'clone' "$clone exists, is not empty and is not a git clone" 'rerun with CURSUS_DIR set to another folder'
        }
        $code = Invoke-Logged 'clone' $git @('clone', $cloneUrl, $clone)
        if ($code -ne 0) { Stop-Setup 'clone' 'git clone failed (log above)' "git clone $cloneUrl $clone" }
        Say "clone: cloned $cloneUrl into $clone"
    }
    $prepare = Join-Path $clone 'setup\student\prepare.py'
    if (-not (Test-Path $prepare)) {
        Stop-Setup 'clone' "$clone has no setup\student\prepare.py: it predates this setup" "cd $clone; git pull; then rerun"
    }

    # --- 8 and 9. Prepare the repository, then the setup check (shared with install.sh) ------
    $uv = Find-Tool 'uv'
    $prepArgs = @('run', '--no-project', '--python', '3.12', 'python', $prepare, '--repo', $clone)
    if ($noLogin) {
        Say 'setup check: skipped (-NoLogin)'
        $prepArgs += '--no-check'
    }
    & $uv @prepArgs
    if ($LASTEXITCODE -ne 0) { $State.Code = 1; return }
    Say "Done: the course is in $clone. Open a new PowerShell window so that Path includes the new tools."
}

$cursusState = @{ Yes = [bool]$Yes; Agent = $Agent; NoLogin = [bool]$NoLogin; DryRun = [bool]$DryRun; Dir = $Dir
    ScriptRoot = $PSScriptRoot; Code = 0; Work = '' }
try {
    Invoke-CursusSetup $cursusState
} catch {
    if ([string]$_ -ne 'cursus-setup-stopped') { [Console]::Out.WriteLine('[setup] FAILED: ' + $_) }
    $cursusState.Code = 1
} finally {
    if ($cursusState.Work -and (Test-Path $cursusState.Work)) { Remove-Item -Recurse -Force $cursusState.Work -ErrorAction SilentlyContinue }
}
Remove-Item Function:\Invoke-CursusSetup -ErrorAction SilentlyContinue
if ($PSCommandPath -and [System.IO.Path]::GetFileName($PSCommandPath) -eq 'install.ps1') { exit $cursusState.Code }
$global:LASTEXITCODE = $cursusState.Code
