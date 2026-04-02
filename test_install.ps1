# ┌─────────────────────────────────────────────┐
# │  install.ps1 test suite                      │
# │  Run: powershell -ExecutionPolicy Bypass -File test_install.ps1
# └─────────────────────────────────────────────┘
$ErrorActionPreference = "Continue"

$script:Pass = 0
$script:Fail = 0
$script:Total = 0

function Ok($m)   { $script:Pass++; $script:Total++; Write-Host "  PASS $m" -ForegroundColor Green }
function Fail($m) { $script:Fail++; $script:Total++; Write-Host "  FAIL $m" -ForegroundColor Red }
function Info($m) { Write-Host "`n▶ $m" -ForegroundColor Yellow }

$TestBinDir = "$env:USERPROFILE\.local\bin"
$TestKimDir = "$env:USERPROFILE\.kim"
$Installer = "$PSScriptRoot\install.ps1"

# ── Pre-flight ────────────────────────────────────────────────────────────────
Info "Pre-flight checks"

if (-not (Test-Path $Installer)) {
    Write-Host "install.ps1 not found at $Installer" -ForegroundColor Red
    exit 1
}
Ok "install.ps1 exists"

$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") {
            $pythonCmd = $cmd
            Ok "$cmd — $ver"
            break
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "Python 3 not found — cannot run tests" -ForegroundColor Red
    exit 1
}

# ── Cleanup function ──────────────────────────────────────────────────────────
function Cleanup {
    Info "Cleaning up test artifacts"
    # Stop any running daemon
    if (Test-Path "$TestKimDir\kim.pid") {
        $pid = Get-Content "$TestKimDir\kim.pid" 2>$null
        if ($pid) { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue }
        Remove-Item "$TestKimDir\kim.pid" -Force -ErrorAction SilentlyContinue
    }
    # Remove scheduled task
    Unregister-ScheduledTask -TaskName "KimReminder" -Confirm:$false -ErrorAction SilentlyContinue
    # Remove binary shim
    Remove-Item "$TestBinDir\kim.bat" -Force -ErrorAction SilentlyContinue
    # Remove data dir
    if (Test-Path $TestKimDir) { Remove-Item $TestKimDir -Recurse -Force -ErrorAction SilentlyContinue }
}

Cleanup

# ── Test 1: Local install (KIM_LOCAL=1) ──────────────────────────────────────
Info "Test 1: Local install from source"

$env:KIM_LOCAL = "1"
$output = & powershell -ExecutionPolicy Bypass -File $Installer 2>&1
$env:KIM_LOCAL = $null

if ($output -match "Installed to|Copied kim package") {
    Ok "Install completed without fatal error"
} else {
    Fail "Install output missing success indicator"
    Write-Host ($output -join "`n") -ForegroundColor DarkGray
}

if (Test-Path "$TestBinDir\kim.bat") {
    Ok "Binary shim created at $TestBinDir\kim.bat"
} else {
    Fail "Binary shim not found at $TestBinDir\kim.bat"
}

if (Test-Path "$TestKimDir\kim.py") {
    Ok "kim.py installed to $TestKimDir\kim.py"
} else {
    Fail "kim.py not found at $TestKimDir\kim.py"
}

if (Test-Path "$TestKimDir\kim") {
    Ok "kim package folder installed to $TestKimDir\kim"
} else {
    Fail "kim package folder not found at $TestKimDir\kim"
}

# ── Test 2: kim binary works ─────────────────────────────────────────────────
Info "Test 2: kim binary executes correctly"

if (Test-Path "$TestBinDir\kim.bat") {
    $versionOutput = & "$TestBinDir\kim.bat" --version 2>&1
    if ($versionOutput -match "kim") {
        Ok "kim --version works: $versionOutput"
    } else {
        Fail "kim --version failed: $versionOutput"
    }

    $helpOutput = & "$TestBinDir\kim.bat" --help 2>&1
    if ($helpOutput -match "commands:") {
        Ok "kim --help shows commands"
    } else {
        Fail "kim --help missing commands section"
    }

    $statusOutput = & "$TestBinDir\kim.bat" status 2>&1
    if ($statusOutput -match "kim") {
        Ok "kim status works"
    } else {
        Fail "kim status failed: $statusOutput"
    }
} else {
    Fail "Binary shim missing, skipping execution tests"
}

# ── Test 3: Idempotent re-install ────────────────────────────────────────────
Info "Test 3: Idempotent re-install (run install again)"

$env:KIM_LOCAL = "1"
$output2 = & powershell -ExecutionPolicy Bypass -File $Installer 2>&1
$env:KIM_LOCAL = $null

if ($output2 -match "Installed to|Copied kim package") {
    Ok "Re-install completed without fatal error"
} else {
    Fail "Re-install output missing success indicator"
}

if ((Test-Path "$TestBinDir\kim.bat") -and (Test-Path "$TestKimDir\kim.py")) {
    Ok "Files still present after re-install"
} else {
    Fail "Files missing after re-install"
}

# ── Test 4: --uninstall flag works ───────────────────────────────────────────
Info "Test 4: --uninstall flag removes everything"

$output3 = & powershell -ExecutionPolicy Bypass -File $Installer --uninstall 2>&1

if ($output3 -match "uninstalled") {
    Ok "Uninstall completed successfully"
} else {
    Fail "Uninstall output missing success indicator: $output3"
}

if (-not (Test-Path "$TestBinDir\kim.bat")) {
    Ok "Binary shim removed"
} else {
    Fail "Binary shim still exists after uninstall"
}

if (-not (Test-Path $TestKimDir)) {
    Ok "Data directory removed"
} else {
    Fail "Data directory still exists after uninstall"
}

# ── Test 5: Install after uninstall (full cycle) ─────────────────────────────
Info "Test 5: Install after uninstall (full cycle)"

$env:KIM_LOCAL = "1"
$output4 = & powershell -ExecutionPolicy Bypass -File $Installer 2>&1
$env:KIM_LOCAL = $null

if ($output4 -match "Installed to|Copied kim package") {
    Ok "Install after uninstall succeeded"
} else {
    Fail "Install after uninstall failed: $output4"
}

if (Test-Path "$TestBinDir\kim.bat") {
    $versionAfter = & "$TestBinDir\kim.bat" --version 2>&1
    if ($versionAfter -match "kim") {
        Ok "kim works after full cycle: $versionAfter"
    } else {
        Fail "kim broken after full cycle: $versionAfter"
    }
} else {
    Fail "Binary shim missing after full cycle"
}

# ── Test 6: Config file created ──────────────────────────────────────────────
Info "Test 6: Config file created"

if (Test-Path "$TestKimDir\config.json") {
    Ok "Config file created at $TestKimDir\config.json"
    $config = Get-Content "$TestKimDir\config.json" | ConvertFrom-Json
    if ($config.reminders) {
        Ok "Config has reminders array"
    } else {
        Fail "Config missing reminders array"
    }
} else {
    Fail "Config file not created"
}

# ── Cleanup ───────────────────────────────────────────────────────────────────
Cleanup

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════" -ForegroundColor Blue
Write-Host "  Results: $script:Pass passed, $script:Fail failed, $script:Total total" -ForegroundColor Blue
Write-Host "═══════════════════════════════════════════" -ForegroundColor Blue

if ($script:Fail -gt 0) {
    exit 1
}
