# 注册看门狗计划任务：登录时 + 之后每 1 分钟跑一次 windows\watchdog.ps1
# （实测 2 分钟节奏下"卡死两轮确认才重启"要 3 分 41 秒，超出 3 分钟目标，故收紧到 1 分钟）
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'watchdog.ps1'
if (-not (Test-Path $script)) { throw "missing $script" }
$action  = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $script + '"')
$tLogon  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# 1 分钟一轮（IgnoreNew 保证不并发）；更频繁的 wsl.exe 调用顺带把 WSL 虚拟机也保活了
$tRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'WeChatBotWatchdog' -Action $action -Trigger $tLogon, $tRepeat -Settings $settings -Principal $principal -Description 'Self-heal the resident WeChat bot (WSL keepalive + systemd services + health log)' -Force | Select-Object TaskName, State | Format-List
