# 注册「登录时」计划任务：静默维持 WSL2 常驻（微信机器人需要 WSL 一直活着）
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File windows\register-keepalive-task.ps1
$ErrorActionPreference = 'Stop'
$vbs = Join-Path $PSScriptRoot 'wsl-keepalive.vbs'
if (-not (Test-Path $vbs)) { throw "missing $vbs" }
$action  = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('"' + $vbs + '"')
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'WeChatBotKeepAlive' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Keep WSL2 VM alive so the WeChat resident bot keeps running' -Force | Select-Object TaskName, State | Format-List
