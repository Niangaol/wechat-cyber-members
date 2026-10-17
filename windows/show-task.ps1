# 查看两个计划任务的实际触发器/设置（PowerShell 输出中文不乱码）
[Console]::OutputEncoding = [Text.Encoding]::UTF8
foreach ($name in @('WeChatBotKeepAlive', 'WeChatBotWatchdog')) {
    Write-Output ('=== ' + $name)
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $t) { Write-Output '  (不存在)'; continue }
    Write-Output ('  State      : ' + $t.State)
    foreach ($tr in $t.Triggers) {
        if ($tr.Repetition -and $tr.Repetition.Interval) {
            Write-Output ('  Repetition : ' + $tr.Repetition.Interval + ' (duration ' + $tr.Repetition.Duration + ')')
        } else {
            Write-Output ('  Trigger    : ' + $tr.CimClass.CimClassName)
        }
    }
    Write-Output ('  ExecLimit  : ' + $t.Settings.ExecutionTimeLimit)
    Write-Output ('  MultiInst  : ' + $t.Settings.MultipleInstances)
    $info = Get-ScheduledTaskInfo -TaskName $name
    Write-Output ('  NextRun    : ' + $info.NextRunTime)
    Write-Output ('  LastRun    : ' + $info.LastRunTime + ' (result ' + $info.LastTaskResult + ')')
}
