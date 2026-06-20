param(
    [string]$HostName = "64.83.34.222",
    [string]$DeployUser = "root",
    [string]$RemoteRoot = "/opt/binance-futures-agent",
    [string]$RemoteEtc = "/etc/binance-futures-agent",
    [string]$Variant = "quant_setup_selective_guarded",
    [string]$Interval = "5m",
    [string]$ManualExposureSymbols = "ETHUSDT",
    [string]$MatrixReport = "",
    [string]$Since = "",
    [int]$MinOutcomes = 20,
    [double]$MinWinRate = 0.5,
    [double]$MinProfitFactor = 1.1,
    [double]$MaxWorstDrawdownUsdt = 1.5,
    [string]$OutputPath = "",
    [switch]$Run,
    [switch]$AllowPasswordPrompt,
    [switch]$SkipBinance
)

$ErrorActionPreference = "Stop"

function Assert-IsolatedTarget {
    param(
        [string]$Root,
        [string]$Etc
    )
    if ($Root -ne "/opt/binance-futures-agent") {
        throw "Refusing non-isolated RemoteRoot: $Root"
    }
    if ($Etc -ne "/etc/binance-futures-agent") {
        throw "Refusing non-isolated RemoteEtc: $Etc"
    }
}

function Quote-Remote {
    param([string]$Value)
    return "'" + $Value.Replace("'", "'`"`"'`"'" ) + "'"
}

function New-DefaultOutputPath {
    $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    $runtime = Join-Path $projectRoot "runtime"
    $timestamp = Get-Date -Format "yyyyMMddTHHmmss"
    return Join-Path $runtime "server-live-resume-readiness-$timestamp.json"
}

Assert-IsolatedTarget -Root $RemoteRoot -Etc $RemoteEtc

$Target = "${DeployUser}@${HostName}"
$remotePython = "$RemoteRoot/.venv/bin/python"
$remoteApp = "$RemoteRoot/app"
$remoteDb = "$RemoteRoot/data/agent.sqlite"
$remoteEnv = "$RemoteEtc/env"

$readinessArgs = @(
    "-m", "bfa.cli",
    "ops", "live-resume-readiness",
    "--env-file", $remoteEnv,
    "--db", $remoteDb,
    "--variant", $Variant,
    "--interval", $Interval,
    "--manual-exposure-symbols", $ManualExposureSymbols,
    "--target-profile", "30u_10x_multi_dynamic",
    "--allow-two-positions",
    "--min-outcomes", [string]$MinOutcomes,
    "--min-win-rate", [string]$MinWinRate,
    "--min-profit-factor", [string]$MinProfitFactor,
    "--max-worst-drawdown-usdt", [string]$MaxWorstDrawdownUsdt
)

if ($MatrixReport) {
    $readinessArgs += @("--matrix-report", $MatrixReport)
}
if ($Since) {
    $readinessArgs += @("--since", $Since)
}
if ($SkipBinance) {
    $readinessArgs += "--skip-binance"
}

$remoteCommand = "cd $(Quote-Remote $remoteApp) && $(Quote-Remote $remotePython) " +
    (($readinessArgs | ForEach-Object { Quote-Remote $_ }) -join " ")

Write-Host "Readiness target: $Target"
Write-Host "Remote root: $RemoteRoot"
Write-Host "Remote env: $RemoteEtc/env"
Write-Host "Manual exposure symbols: $ManualExposureSymbols"
Write-Host "Variant: $Variant"
Write-Host "Command: $remoteCommand"

if (-not $Run) {
    Write-Host "Preview only. Re-run with -Run after reviewing the command."
    exit 0
}

if (-not $OutputPath) {
    $OutputPath = New-DefaultOutputPath
}

$outputDir = Split-Path -Parent $OutputPath
if ($outputDir) {
    New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
}

$stdoutFile = New-TemporaryFile
$stderrFile = New-TemporaryFile
try {
    $sshArgs = @()
    if (-not $AllowPasswordPrompt) {
        $sshArgs += @("-o", "BatchMode=yes")
    }
    $sshArgs += @($Target, $remoteCommand)

    & ssh @sshArgs 1>$stdoutFile 2>$stderrFile
    $exitCode = $LASTEXITCODE
    $stdoutText = Get-Content -LiteralPath $stdoutFile -Raw
    $stderrText = Get-Content -LiteralPath $stderrFile -Raw

    if ($exitCode -ne 0 -and $exitCode -ne 1) {
        if ($stderrText) {
            Write-Warning "Remote readiness command failed before producing a valid readiness result."
        }
        throw "Remote readiness command failed with exit code $exitCode"
    }

    try {
        $payload = $stdoutText | ConvertFrom-Json
    }
    catch {
        throw "Remote readiness stdout was not valid JSON."
    }

    if ($payload.schema -ne "bfa_live_resume_readiness_v1") {
        throw "Unexpected readiness schema: $($payload.schema)"
    }

    $stdoutText | Set-Content -LiteralPath $OutputPath -Encoding UTF8

    Write-Host "Readiness artifact: $OutputPath"
    Write-Host "Readiness status: $($payload.status)"
    Write-Host "Live resume allowed: $($payload.live_resume_allowed)"
    Write-Host "Read-only places_orders: $($payload.read_only.places_orders)"
    Write-Host "Read-only changes_systemd_state: $($payload.read_only.changes_systemd_state)"
    if ($stderrText) {
        Write-Warning "Remote command wrote stderr; artifact was still parsed from stdout."
    }
}
finally {
    Remove-Item -LiteralPath $stdoutFile, $stderrFile -Force -ErrorAction SilentlyContinue
}
