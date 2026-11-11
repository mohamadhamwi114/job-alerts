# Creates/updates a Task Scheduler task that runs run_local.ps1 at logon and every 30 min, waking the PC from sleep.
$taskName = "LinkedInJobAlerts"
$script = Join-Path $PSScriptRoot "run_local.ps1"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $PSScriptRoot
$every30 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$atLogon.Delay = "PT2M"  # let Wi-Fi connect first
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($every30, $atLogon) -Settings $settings `
    -Description "LinkedIn job alerts -> Telegram + Google Sheet" -Force | Out-Null
Write-Host "Registered '$taskName': at logon (+2 min) and every 30 min, wakes from sleep."
Write-Host "Remove with: Unregister-ScheduledTask $taskName -Confirm:`$false"
