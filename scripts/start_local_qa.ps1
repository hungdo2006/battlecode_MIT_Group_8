# One-click isolated local Account-Only preview for Windows PowerShell 5.1+.
# Requires Docker Desktop (Linux containers). Does not touch the default Compose project.
[CmdletBinding()]
param(
    [switch] $Stop,
    [switch] $SkipPull,
    [switch] $NoBrowser
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$project = "neon-arena-click-qa"
$port = 18042
$url = "http://127.0.0.1:$port"
$adminUsername = "qa.admin"

if (-not $env:LOCALAPPDATA) {
    Write-Host "ERROR: LOCALAPPDATA is unavailable. This launcher requires Windows."
    exit 1
}
$stateDir = Join-Path $env:LOCALAPPDATA "NEON_ARENA\click-qa"
$envFile = Join-Path $stateDir "qa.env"
$overrideFile = Join-Path $stateDir "compose.qa.yaml"
$buildMarker = Join-Path $stateDir "built-commit.txt"
$baseFile = Join-Path $root "compose.yaml"
$botImage = "neon-arena-click-qa-bot:4.2"
$controllerImage = "neon-arena-click-qa-controller:4.2"
$arenaImage = "neon-arena-click-qa-arena:4.2"

function Ensure-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI not found. Install and start Docker Desktop (Linux containers)."
    }
    & docker compose version
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose v2 is required."
    }
    $engine = & docker info --format '{{.OSType}}' 2>$null
    if ($LASTEXITCODE -ne 0 -or ($engine | Select-Object -Last 1) -ne "linux") {
        throw "Docker Desktop is not running in Linux containers mode."
    }
}

function Compose-Checked {
    param([Parameter(Mandatory = $true)][string[]] $Arguments)
    $all = $script:composeBase + $Arguments
    & docker @all
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose failed: $($Arguments -join ' ') (exit $LASTEXITCODE)"
    }
}

function Probe-Python {
    param([Parameter(Mandatory = $true)][string] $Source)
    $all = $script:composeBase + @("run", "-T", "--rm", "--no-deps", "arena", "python", "-")
    $Source | & docker @all
    return $LASTEXITCODE
}

try {
    if (-not (Test-Path -LiteralPath $baseFile)) {
        throw "Cannot find compose.yaml. Run the launcher from the NEON ARENA repository."
    }
    Ensure-Docker

    if ($Stop) {
        if (-not (Test-Path -LiteralPath $envFile) -or -not (Test-Path -LiteralPath $overrideFile)) {
            Write-Host "This QA environment has not been initialized. Nothing to stop."
            exit 0
        }
        $script:composeBase = @(
            "compose", "--project-directory", $root,
            "--env-file", $envFile, "-p", $project,
            "-f", $baseFile, "-f", $overrideFile
        )
        Compose-Checked -Arguments @("down")
        Write-Host "NEON ARENA local QA stopped. All QA data volumes are preserved."
        exit 0
    }

    # Only preview the reviewed/stable main branch. Do not silently switch away
    # from a developer's feature branch and do not build unfinished D1 work.
    $commit = "no-git"
    $dirty = $true
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $currentBranch = (& git -C $root branch --show-current 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -eq 0 -and $currentBranch) {
            $currentBranch = $currentBranch.Trim()
            if ($currentBranch -ne "main") {
                throw "Current Git branch is '$currentBranch'. Run 'git switch main' first. The one-click preview only runs merged main."
            }
            $changes = @(& git -C $root status --porcelain --untracked-files=no)
            if ($LASTEXITCODE -ne 0) {
                throw "Cannot inspect Git working tree; refusing to update automatically."
            }
            $dirty = $changes.Count -gt 0
            if (-not $SkipPull -and -not $dirty) {
                Write-Host "[1/5] Syncing origin/main (fast-forward only)..."
                & git -C $root pull --ff-only origin main
                if ($LASTEXITCODE -ne 0) {
                    Write-Warning "Could not fast-forward main. Continuing with the existing local checkout; no reset or forced checkout occurred."
                }
            } elseif ($dirty) {
                Write-Warning "Tracked local edits detected; leaving your files unchanged and skipping Git pull."
            }
            $commit = (& git -C $root rev-parse HEAD | Select-Object -First 1).Trim()
        } else {
            Write-Warning "No Git checkout detected; building the files present in this folder."
        }
    } else {
        Write-Warning "Git unavailable: launching current local files without synchronization."
    }

    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    if (-not (Test-Path -LiteralPath $envFile)) {
        # Never put the runner token in Git, Docker Compose arguments or console logs.
        $buffer = New-Object byte[] 32
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
        $token = ([BitConverter]::ToString($buffer)).Replace("-", "").ToLowerInvariant()
        $content = @(
            "ARENA_RUNNER_TOKEN=$token",
            "ARENA_BIND_IP=127.0.0.1",
            "ARENA_PORT=$port",
            "ARENA_ACCOUNT_AUTH=1",
            "ARENA_ACCOUNT_ONLY=1",
            "ARENA_AUTH_ALLOW_HTTP=1",
            "ARENA_AUTH_ORIGINS=$url",
            "ARENA_READ_ONLY=0",
            "SANDBOX_NAMESPACE=$project"
        ) -join [Environment]::NewLine
        [System.IO.File]::WriteAllText($envFile, $content + [Environment]::NewLine,
            (New-Object System.Text.ASCIIEncoding))
        Write-Host "Created local-only QA configuration in LOCALAPPDATA."
    }
    $override = @"
services:
  bot-image:
    image: $botImage
  controller:
    image: $controllerImage
    environment:
      SANDBOX_IMAGE: $botImage
  arena:
    image: $arenaImage
"@
    [System.IO.File]::WriteAllText($overrideFile, $override + [Environment]::NewLine,
        (New-Object System.Text.UTF8Encoding($false)))

    $script:composeBase = @(
        "compose", "--project-directory", $root,
        "--env-file", $envFile, "-p", $project,
        "-f", $baseFile, "-f", $overrideFile
    )

    Write-Host "[2/5] Checking dedicated Docker images..."
    $imagesReady = $true
    foreach ($image in @($botImage, $controllerImage, $arenaImage)) {
        & docker image inspect $image --format '{{.Id}}' 1>$null 2>$null
        if ($LASTEXITCODE -ne 0) { $imagesReady = $false }
    }
    $lastBuilt = ""
    if (Test-Path -LiteralPath $buildMarker) {
        $lastBuilt = (Get-Content -LiteralPath $buildMarker -Raw).Trim()
    }
    $needsBuild = (-not $imagesReady) -or ($lastBuilt -ne $commit) -or $dirty
    if ($needsBuild) {
        # Never migrate while our own backend is running; do not stop other projects.
        $all = $script:composeBase + @("ps", "--status", "running", "--services")
        $running = @(& docker @all)
        if ($LASTEXITCODE -ne 0) {
            throw "Cannot inspect local QA containers."
        }
        if ($running.Count -gt 0) {
            Write-Host "Updating dedicated QA containers without deleting volumes..."
            Compose-Checked -Arguments @("down")
        }
        Write-Host "Building isolated backend, controller and bot images..."
        Compose-Checked -Arguments @("build", "bot-image", "controller", "arena")
        [System.IO.File]::WriteAllText($buildMarker, $commit + [Environment]::NewLine)
    } else {
        Write-Host "QA images already match local checkout; build skipped."
    }

    Write-Host "[3/5] Checking isolated SQLite database..."
    $dbProbe = @'
from pathlib import Path
import sys
sys.exit(0 if Path("/app/data/arena.sqlite3").exists() else 15)
'@
    $dbExit = Probe-Python -Source $dbProbe
    if ($dbExit -eq 15) {
        Write-Host "First run: creating a fresh QA database (not the default volume)."
        Compose-Checked -Arguments @("run", "--rm", "--no-deps", "arena",
            "python", "-m", "backend.admin_cli", "--data-dir", "/app/data", "migrate")
    } elseif ($dbExit -ne 0) {
        throw "Unable to inspect QA database (exit $dbExit). No migration performed."
    }
    # Existing schemas are NEVER auto-upgraded. A deliberate offline migration
    # with backup is required when a future main release changes schema version.
    Compose-Checked -Arguments @("run", "--rm", "--no-deps", "arena",
        "python", "-m", "backend.admin_cli", "--data-dir", "/app/data", "check")

    Write-Host "[4/5] Checking QA Admin account..."
    $adminProbe = @'
from backend.account_database import AccountDatabase
import sys
with AccountDatabase("/app/data").read() as conn:
    row = conn.execute("SELECT status FROM users WHERE username=? AND system_role='ADMIN'", ("qa.admin",)).fetchone()
if row is None:
    sys.exit(16)
if row[0] != "ACTIVE":
    sys.exit(17)
sys.exit(0)
'@
    $adminExit = Probe-Python -Source $adminProbe
    if ($adminExit -eq 16) {
        Write-Host "First run: create your QA Admin password (hidden input)."
        Compose-Checked -Arguments @("run", "--rm", "--no-deps", "arena", "python",
            "-m", "backend.admin_cli", "--data-dir", "/app/data", "create-admin",
            "--username", $adminUsername, "--display-name", "QA Admin")
    } elseif ($adminExit -eq 17) {
        throw "QA Admin exists but is disabled. Refusing to create or overwrite an account."
    } elseif ($adminExit -ne 0) {
        throw "Unable to verify the QA Admin (exit $adminExit)."
    }

    Write-Host "[5/5] Starting NEON ARENA on $url ..."
    Compose-Checked -Arguments @("up", "-d", "--wait")
    $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 12
    if ($health.status -ne "ok" -or $health.account_only -ne $true -or
        $health.account_auth -ne $true -or $health.runner.ready -ne $true) {
        throw "Health check incomplete (expected ok, account_only, account_auth and runner.ready). Review logs."
    }

    Write-Host ""
    Write-Host "SUCCESS! NEON ARENA local QA is running."
    Write-Host "Address:       $url"
    Write-Host "Admin account: $adminUsername"
    Write-Host "Password:      the one you entered at first setup (not stored by this script)"
    Write-Host "Stop:          double-click Stop-NEON-ARENA-QA.bat"
    Write-Host "Data:          separate Docker volumes; no real/AWS data was touched."
    if (-not $NoBrowser) {
        try { Start-Process $url } catch { Write-Warning "Open this URL manually: $url" }
    }
    exit 0
} catch {
    Write-Host ""
    Write-Host "NEON ARENA one-click startup stopped safely." -ForegroundColor Red
    Write-Host ("Reason: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host "Tip: run 'docker compose ... logs' only for this QA project, or share this window's error."
    exit 1
}
