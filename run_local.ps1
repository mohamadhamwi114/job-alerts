Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force logs | Out-Null
$log = "logs\run_$(Get-Date -Format yyyy-MM-dd).log"
# cmd handles the redirect: PowerShell 5.1 turns native stderr into error records.
cmd /c "`".venv\Scripts\python.exe`" job_alerts.py --runner local >> `"$log`" 2>&1"
