# ═══════════════════════════════════════════════════════════════════════════════
#  Untis Monitor – Windows Task Scheduler Einrichtung
#  Führt das Skript automatisch beim Systemstart aus (als Hintergrundprozess).
#  Ausführen:  PowerShell als Administrator → .\setup_windows_task.ps1
# ═══════════════════════════════════════════════════════════════════════════════

$TaskName = "UntisMonitor"
$ScriptPath = "$PSScriptRoot\untis_monitor.py"
$PythonPath = (Get-Command python).Source

if (-not (Test-Path $ScriptPath)) {
    Write-Error "untis_monitor.py nicht gefunden unter: $ScriptPath"
    exit 1
}

# Task erstellen (startet beim Boot, läuft dauerhaft im Hintergrund)
$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$ScriptPath`"" -WorkingDirectory "$PSScriptRoot"
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description "Überwacht WebUntis-Stundenplan auf Änderungen und sendet Benachrichtigungen" -Force

Write-Host "✓ Task '$TaskName' wurde eingerichtet." -ForegroundColor Green
Write-Host "  Python:   $PythonPath"
Write-Host "  Skript:   $ScriptPath"
Write-Host ""
Write-Host "Task starten:        Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Task anhalten:       Stop-ScheduledTask -TaskName '$TaskName'"
Write-Host "Task löschen:        Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
Write-Host "Status prüfen:       Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "Logs ansehen:        Get-Content "$PSScriptRoot\untis_monitor.log" -Tail 20
