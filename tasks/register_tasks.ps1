# Registers two Windows scheduled tasks:
#   NFL-Rankings-Tuesday  - Tue 07:00  (fetch completed-week actuals, evaluate, push)
#   NFL-Rankings-Thursday - Thu 12:00  (snapshot weekly rankings before games, push)
# Run:  powershell -ExecutionPolicy Bypass -File tasks\register_tasks.ps1

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

schtasks /Create /F /TN "NFL-Rankings-Tuesday" /TR "`"$here\run_tuesday.cmd`"" /SC WEEKLY /D TUE /ST 07:00
schtasks /Create /F /TN "NFL-Rankings-Thursday" /TR "`"$here\run_thursday.cmd`"" /SC WEEKLY /D THU /ST 12:00

Write-Host "Registered. Verify with: schtasks /Query /TN NFL-Rankings-Tuesday"
