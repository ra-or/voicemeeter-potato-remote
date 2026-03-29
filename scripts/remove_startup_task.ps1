$ErrorActionPreference = "Stop"

$startupEntryName = "VoicemeeterPotatoRemote"
$runKeyPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

$existingEntry = Get-ItemProperty -Path $runKeyPath -Name $startupEntryName -ErrorAction SilentlyContinue
if (-not $existingEntry) {
    Write-Host "No startup entry named '$startupEntryName' was found."
    exit 0
}

Remove-ItemProperty -Path $runKeyPath -Name $startupEntryName
Write-Host "Startup entry '$startupEntryName' removed."
