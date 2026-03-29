param(
    [switch]$Foreground,
    [int]$DelaySeconds = 0
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
$configPath = Join-Path $projectRoot "config.json"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logsDir = Join-Path $projectRoot "logs"
$stdoutLog = Join-Path $logsDir "server.log"
$stderrLog = Join-Path $logsDir "server-error.log"

if ($DelaySeconds -gt 0) {
    Start-Sleep -Seconds $DelaySeconds
}

if (-not (Test-Path $venvPython)) {
    throw "Python virtual environment not found at '$venvPython'. Create it first with: python -m venv .venv"
}

if (-not (Test-Path $configPath)) {
    throw "config.json was not found at '$configPath'."
}

$config = Get-Content $configPath -Raw | ConvertFrom-Json
$port = 8787
if ($null -ne $config.port) {
    $port = [int]$config.port
}

$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    Write-Host "Voicemeeter Potato Remote already appears to be listening on port $port."
    exit 0
}

Set-Location $projectRoot
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null

if ($Foreground) {
    & $venvPython app.py
    exit $LASTEXITCODE
}

Start-Process `
    -FilePath $venvPython `
    -ArgumentList "app.py" `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog | Out-Null

Write-Host "Start request sent. Logs will be written to '$logsDir'."
