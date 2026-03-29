$ErrorActionPreference = "Stop"

$startupEntryName = "VoicemeeterPotatoRemote"
$runKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
$startScript = Join-Path $projectRoot "scripts\start_voicemeeter_remote.ps1"
$powershellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path $startScript)) {
    throw "Startup script not found at '$startScript'."
}

$startupCommand = "`"$powershellExe`" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`" -DelaySeconds 20"

New-Item -Path $runKeyPath -Force | Out-Null
New-ItemProperty `
    -Path $runKeyPath `
    -Name $startupEntryName `
    -Value $startupCommand `
    -PropertyType String `
    -Force | Out-Null

Write-Host "Startup entry '$startupEntryName' installed."
Write-Host "It will launch the app for the current Windows user shortly after logon."
