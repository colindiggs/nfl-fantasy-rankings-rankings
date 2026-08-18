# Registers the capture pipeline with Windows Task Scheduler.
#
#   NFL-Rankings-Sync   daily 12:00, and again at 07:00
#
# One task, run daily, because runner.py is idempotent: every run works out
# what is missing and gets it. That is what makes a missed run survivable.
# The previous setup ran one Thursday task that captured only that day's week,
# with StartWhenAvailable off — so if the machine was asleep at Thursday noon,
# that week's rankings were lost permanently from the sources that publish
# only the current week.
#
# The settings below are the ones that actually matter for unattended running:
#
#   StartWhenAvailable          run a missed task as soon as the PC is back
#   WakeToRun                   wake the machine rather than skip
#   DisallowStartIfOnBatteries  off, so a laptop on battery still runs
#   RestartCount/Interval       retry transient network failures
#
# Run:  powershell -ExecutionPolicy Bypass -File tasks\register_tasks.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$cmd  = Join-Path $here "run_sync.cmd"
$name = "NFL-Rankings-Sync"

if (-not (Test-Path $cmd)) { throw "missing $cmd" }

# midday catches the Tue-Thu pre-kickoff window; the early run picks up
# actuals and repairs anything the previous day missed
$triggers = @(
  (New-ScheduledTaskTrigger -Daily -At 7:00am),
  (New-ScheduledTaskTrigger -Daily -At 12:00pm)
)

$action = New-ScheduledTaskAction -Execute $cmd

$settings = New-ScheduledTaskSettingsSet `
  -StartWhenAvailable `
  -WakeToRun `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 20) `
  -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
  -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers `
  -Settings $settings -Description "Capture NFL rankings, score them, publish to GitHub Pages" -Force | Out-Null

# the day-named tasks are superseded by the idempotent daily sync
foreach ($old in "NFL-Rankings-Tuesday", "NFL-Rankings-Thursday") {
  if (Get-ScheduledTask -TaskName $old -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $old -Confirm:$false
    Write-Host "removed superseded task $old"
  }
}

Write-Host "Registered $name (daily 07:00 and 12:00, wakes the machine, catches up missed runs)."
Get-ScheduledTask -TaskName $name | Get-ScheduledTaskInfo | Format-List TaskName, NextRunTime
