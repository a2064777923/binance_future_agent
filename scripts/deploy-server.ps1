param(
    [string]$HostName = "64.83.34.222",
    [string]$DeployUser = "root",
    [string]$RemoteRoot = "/opt/binance-futures-agent",
    [string]$RemoteEtc = "/etc/binance-futures-agent",
    [switch]$Apply,
    [switch]$CheckNetwork
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

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments)
    Write-Host ">> $FilePath $($Arguments -join ' ')"
    if ($Apply) {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$FilePath failed with exit code $LASTEXITCODE"
        }
    }
}

Assert-IsolatedTarget -Root $RemoteRoot -Etc $RemoteEtc

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ArchivePath = Join-Path ([System.IO.Path]::GetTempPath()) "binance-futures-agent-source.tar.gz"
$RemoteArchive = "/tmp/binance-futures-agent-source.tar.gz"
$RemoteBootstrap = "/tmp/binance-futures-agent-bootstrap.sh"
$Target = "${DeployUser}@${HostName}"

Push-Location $ProjectRoot
try {
    Invoke-Checked -FilePath "git" -Arguments @("archive", "--format=tar.gz", "-o", $ArchivePath, "HEAD")
}
finally {
    Pop-Location
}

Write-Host "Deployment target: $Target"
Write-Host "Remote root: $RemoteRoot"
Write-Host "Remote env: $RemoteEtc/env"
Write-Host "Archive: $ArchivePath"

if (-not $Apply) {
    Write-Host "Preview only. Re-run with -Apply after reviewing the commands."
}

Invoke-Checked -FilePath "scp" -Arguments @($ArchivePath, "${Target}:$RemoteArchive")
Invoke-Checked -FilePath "scp" -Arguments @((Join-Path $ProjectRoot "deploy\remote-bootstrap.sh"), "${Target}:$RemoteBootstrap")

$BootstrapCommand = "BFA_DEPLOY_ROOT='$RemoteRoot' BFA_ETC_DIR='$RemoteEtc' bash '$RemoteBootstrap' '$RemoteArchive'"
Invoke-Checked -FilePath "ssh" -Arguments @($Target, $BootstrapCommand)

$HealthArgs = "--env-file $RemoteEtc/env --db $RemoteRoot/data/agent.sqlite"
if ($CheckNetwork) {
    $HealthArgs = "$HealthArgs --check-binance --check-openai"
}
else {
    $HealthArgs = "$HealthArgs --skip-network"
}
$HealthCommand = "$RemoteRoot/.venv/bin/python -m bfa.cli ops health-check $HealthArgs"
Invoke-Checked -FilePath "ssh" -Arguments @($Target, $HealthCommand)

Write-Host "Deploy script complete. Keep BFA_MODE=dry_run until server health checks are reviewed."
