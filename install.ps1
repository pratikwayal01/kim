# ┌─────────────────────────────────────────────┐
# │  kim — keep in mind                         │
# │  installer for Windows (PowerShell)         │
# └─────────────────────────────────────────────┘
# Run: powershell -ExecutionPolicy Bypass -File install.ps1
param()
$ErrorActionPreference = "Stop"

function Info($m)   { Write-Host "→ $m" -ForegroundColor Cyan }
function Ok($m)     { Write-Host "✓ $m" -ForegroundColor Green }
function Warn($m)   { Write-Host "! $m" -ForegroundColor Yellow }
function Hdr($m)    { Write-Host "`n$m`n$('─'*40)" -ForegroundColor Blue }
function Err($m)    { Write-Host "✗ $m" -ForegroundColor Red; exit 1 }

$REPO     = "https://raw.githubusercontent.com/pratikwayal01/kim/main"
$KimDir   = "$env:USERPROFILE\.kim"
$BinDir   = "$env:USERPROFILE\.local\bin"
$KimPy    = "$KimDir\kim.py"
$KimBat   = "$BinDir\kim.bat"

Hdr "kim — keep in mind"
Info "OS   : $([Environment]::OSVersion.VersionString)"
Info "Arch : $env:PROCESSOR_ARCHITECTURE"

# ── Python 3 ──────────────────────────────────────────────────────────────────
Hdr "Checking Python 3"
$PythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") {
            $PythonCmd = (Get-Command $cmd).Source
            Ok "$cmd — $ver"
            break
        }
    } catch {}
}

if (-not $PythonCmd) {
    Warn "Python 3 not found."
    $ans = Read-Host "Install via winget? (y/n)"
    if ($ans -eq "y") {
        winget install Python.Python.3 --silent
        $PythonCmd = (Get-Command python).Source
        Ok "Python installed: $PythonCmd"
    } else {
        Err "Python 3 required. Get it at https://python.org"
    }
}

# ── Download kim.py ───────────────────────────────────────────────────────────
Hdr "Installing kim"
New-Item -ItemType Directory -Force -Path $KimDir, $BinDir | Out-Null

$local = $env:KIM_LOCAL -eq "1"
if ($local) {
    $src = Join-Path (Split-Path $MyInvocation.MyCommand.Path) "kim.py"
    Copy-Item $src -Destination $KimPy -Force
    Ok "Copied kim.py from local source"
} else {
    Info "Downloading kim.py..."
    Invoke-WebRequest "$REPO/kim.py" -OutFile $KimPy
    Ok "Downloaded kim.py"
}

# ── Create kim.bat shim ───────────────────────────────────────────────────────
@"
@echo off
"$PythonCmd" "$KimPy" %*
"@ | Set-Content $KimBat
Ok "Created: $KimBat"

# ── Add to PATH if needed ─────────────────────────────────────────────────────
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$BinDir*") {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$BinDir", "User")
    Ok "Added $BinDir to user PATH (restart terminal to apply)"
}

# ── Task Scheduler for autostart ─────────────────────────────────────────────
Hdr "Setting up Task Scheduler"
$TaskName = "KimReminder"

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$action   = New-ScheduledTaskAction -Execute $PythonCmd -Argument "$KimPy start" -WorkingDirectory $KimDir
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "kim reminder daemon" -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2

$state = (Get-ScheduledTask -TaskName $TaskName).State
if ($state -eq "Running") { Ok "Task running ✓" }
else { Warn "Task state: $state — check Task Scheduler manually" }

# ── Done ──────────────────────────────────────────────────────────────────────
Hdr "Done!"
Write-Host "  kim is installed and running.`n"
Write-Host "  Commands:" -ForegroundColor Cyan
Write-Host "    kim status       → show what's running"
Write-Host "    kim list         → list all reminders"
Write-Host "    kim edit         → edit config"
Write-Host "    kim logs         → view recent logs"
Write-Host "    kim stop/start   → control the daemon"
Write-Host ""
Write-Host "  Config: $KimDir\config.json" -ForegroundColor Cyan
Write-Host ""
Ok "Stay healthy. Keep it in mind."
