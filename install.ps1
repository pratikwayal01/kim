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

# ── Download kim package and wrapper ──────────────────────────────────────────
Hdr "Installing kim"
New-Item -ItemType Directory -Force -Path $KimDir, $BinDir | Out-Null

$local = $env:KIM_LOCAL -eq "1"
if ($local) {
    # Copy from local source (for development)
    $srcDir = Split-Path $MyInvocation.MyCommand.Path
    Copy-Item "$srcDir\kim.py" -Destination $KimDir -Force
    Copy-Item "$srcDir\kim" -Destination $KimDir -Recurse -Force
    Ok "Copied kim package from local source"
} else {
    Info "Downloading kim package..."
    $zipUrl = "https://github.com/pratikwayal01/kim/archive/refs/heads/main.zip"
    $zipPath = "$env:TEMP\kim-main.zip"
    $extractPath = "$env:TEMP\kim-extract"
    
    # Download zip
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath
    Ok "Downloaded package"
    
    # Extract zip — GitHub zip contains a kim-main/ subfolder
    if (Test-Path $extractPath) { Remove-Item $extractPath -Recurse -Force }
    Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
    Ok "Extracted package"
    
    # Find the actual source folder — GitHub zip extracts to kim-main/ inside the extract path
    $srcDir = Get-ChildItem -Path $extractPath -Directory | Select-Object -First 1
    if (-not $srcDir) {
        $srcDir = $extractPath
    } else {
        $srcDir = $srcDir.FullName
    }
    
    Write-Host "  Source: $srcDir" -ForegroundColor Gray
    
    # Verify files exist before copying
    if (-not (Test-Path "$srcDir\kim.py")) {
        Err "kim.py not found in $srcDir — extracted contents: $(Get-ChildItem $srcDir | ForEach-Object { $_.Name } | Sort-Object)"
    }
    
    # Copy kim.py and kim/ folder to install directory
    Copy-Item "$srcDir\kim.py" -Destination $KimDir -Force
    Copy-Item "$srcDir\kim" -Destination $KimDir -Recurse -Force
    Ok "Installed to $KimDir"
    
    # Cleanup
    Remove-Item $zipPath -Force
    Remove-Item $extractPath -Recurse -Force
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

# ── Fix pip Scripts PATH (helps users who did pip install without this script) ─
$pipScripts = & $PythonCmd -c "import sysconfig; print(sysconfig.get_path('scripts','nt_user'))" 2>$null
if ($pipScripts -and (Test-Path $pipScripts)) {
    $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if ($userPath -notlike "*$pipScripts*") {
        [Environment]::SetEnvironmentVariable("PATH", "$userPath;$pipScripts", "User")
        $env:PATH += ";$pipScripts"
        Ok "Added pip Scripts dir to PATH: $pipScripts"
    }
}

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
