# 微信机器人常驻看门狗：每 2 分钟自愈一次（注册脚本里设置；任务不允许并发）。
#   1) 没有常驻 WSL 客户端就补一个（没它 WSL2 空闲 60s 会关整台 VM，机器人一起死）
#   2) 两个 systemd 用户服务不在跑就拉起来
#   3) 把一行健康 JSON 写进 logs/watchdog.log，方便回看
#   4) 需要人才能解决的事（掉登录 / 服务起不来 / 心跳卡住）弹 Windows 通知，
#      同类问题 30 分钟只提醒一次，免得刷屏
#   5) WSL 里有下班标记（手动停 / 排班停）就整体待机：不拉服务、不告警、不重启
# 注册：powershell -NoProfile -ExecutionPolicy Bypass -File windows\register-watchdog-task.ps1
# 自测：powershell -NoProfile -ExecutionPolicy Bypass -File windows\watchdog.ps1 -TestToast
param([switch]$TestToast)
$ErrorActionPreference = 'Continue'
# wsl.exe 的 stdout 是 UTF-8，PowerShell 5.1 默认按系统代码页（简中=GBK）解码，
# 于是 health.py 里的中文（下班标记的说明）写进日志全是乱码。显式指定 UTF8。
# 不加这行的话，2026-10-19 之前 logs/watchdog.log 里的中文一直是乱的。
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$Distro = 'Ubuntu-24.04'
$User   = 'niangao'
$Root   = 'D:\AgentPrograms\wechat-bot'
$Log    = Join-Path $Root 'logs\watchdog.log'
$AlertState = Join-Path $Root 'logs\watchdog-alert.json'
$Wsl    = Join-Path $env:SystemRoot 'System32\wsl.exe'
$Health = 'DISPLAY=:99 python3 /mnt/d/AgentPrograms/wechat-bot/wsl/health.py'

function Write-Log([string]$msg) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    # 每 2 分钟一行、长年累月会很大：超过 2MB 就滚一次，只留上一份
    try {
        if ((Test-Path $Log) -and ((Get-Item $Log).Length -gt 2MB)) {
            Move-Item -Path $Log -Destination ($Log + '.1') -Force
        }
    } catch { }
    try { Add-Content -Path $Log -Value $line -Encoding UTF8 } catch { }
}

# 心跳卡住要连续两轮确认才动手重启，避免一轮抖动就重启进程
$HbState = Join-Path $Root 'logs\watchdog-heartbeat.json'

function Step-HeartbeatStreak() {
    $streak = 0
    try {
        if (Test-Path $HbState) { $streak = [int]((Get-Content $HbState -Raw | ConvertFrom-Json).streak) }
    } catch { $streak = 0 }
    $streak = $streak + 1
    try { (@{ streak = $streak; at = (Get-Date).ToString('s') } | ConvertTo-Json) | Set-Content -Path $HbState -Encoding UTF8 } catch { }
    return $streak
}

function Reset-HeartbeatStreak() {
    try { if (Test-Path $HbState) { Remove-Item $HbState -Force } } catch { }
}

function Show-Toast([string]$title, [string]$body) {
    try {
        [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
        [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
        $tpl = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $nodes = $tpl.GetElementsByTagName('text')
        [void]$nodes.Item(0).AppendChild($tpl.CreateTextNode($title))
        [void]$nodes.Item(1).AppendChild($tpl.CreateTextNode($body))
        $toast = New-Object Windows.UI.Notifications.ToastNotification $tpl
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('年糕.Agent').Show($toast)
        Write-Log ('toast shown: ' + $title)
    } catch {
        Write-Log ('toast failed: ' + $_.Exception.Message)
    }
}

function Alert-Once([string]$kind, [string]$title, [string]$body, [int]$everyMinutes = 30) {
    $now = Get-Date
    $last = $null
    try { if (Test-Path $AlertState) { $last = Get-Content $AlertState -Raw | ConvertFrom-Json } } catch { $last = $null }
    if ($last) {
        $prev = $last.$kind
        if ($prev) {
            try { if (($now - [datetime]$prev).TotalMinutes -lt $everyMinutes) { return } } catch { }
        }
    } else {
        $last = New-Object psobject
    }
    Show-Toast $title $body
    $last | Add-Member -NotePropertyName $kind -NotePropertyValue ($now.ToString('s')) -Force
    try { ($last | ConvertTo-Json -Compress) | Set-Content -Path $AlertState -Encoding UTF8 } catch { }
}

if ($TestToast) {
    Show-Toast '年糕.Agent 测试通知' '看到这条，说明掉登录/服务异常时能弹到你屏幕上。'
    exit 0
}

try {
    # 1) 常驻客户端：在发行版内部数 sleep 进程最可靠
    #    （计划任务上下文里 Get-CimInstance 反而看不到 wsl.exe，实测 wsl.exe=0 误报）
    #    （用 ps|grep 而不是 pgrep：实测 pgrep -f 在这个内核上匹配不到 wsl 拉起的 sleep；
    #      命令串单独放变量里，PowerShell 调原生程序时内嵌双引号会被吃掉）
    $countCmd = 'ps -eo cmd | grep -c ''[s]leep 2147483'''
    $n = ((& $Wsl -d $Distro -u $User -e bash -lc $countCmd 2>&1) -join '').Trim()
    if ($n -notmatch '^[0-9]+$') { $n = '0' }
    if ([int]$n -lt 1) {
        Start-Process -FilePath $Wsl -ArgumentList '-d', $Distro, '-u', $User, '-e', 'sleep', '2147483' -WindowStyle Hidden
        Write-Log ('keepalive missing (inside=' + $n + ') -> restarted')
        Start-Sleep -Seconds 6
    } elseif ([int]$n -gt 1) {
        $trimCmd = 'ps -eo pid,cmd | grep ''[s]leep 2147483'' | awk ''{print $1}'' | tail -n +2 | xargs -r kill'
        & $Wsl -d $Distro -u $User -e bash -lc $trimCmd 2>&1 | Out-Null
        Write-Log ('keepalive duplicated (inside=' + $n + ') -> trimmed')
    }

    # 2) systemd 用户服务——但"该不该跑"由 WSL 里的下班标记说了算。
    #    手动停止（botctl.sh stop）和排班停止（bot-schedule.sh stop）都写那个标记。
    #    不看它的话，这里每 2 分钟就把用户刚停掉的机器人拉起来，一键停止等于没停。
    $offlineCmd = 'test -f ~/.local/state/wechat-bot/scheduled-offline.json && echo OFFLINE'
    $off = ((& $Wsl -d $Distro -u $User -e bash -lc $offlineCmd 2>&1) -join ' ') -match 'OFFLINE'
    if ($off) {
        Write-Log 'offline marker present -> skip autostart (manual or scheduled stop)'
    } else {
        $state = (& $Wsl -d $Distro -u $User -e bash -lc 'systemctl --user is-active --quiet wechat-stack wechat-bot && echo ACTIVE' 2>&1) -join ' '
        if ($state -notmatch 'ACTIVE') {
            Write-Log ('services down (' + $state.Trim() + ') -> starting')
            & $Wsl -d $Distro -u $User -e bash -lc 'systemctl --user start wechat-stack wechat-bot' 2>&1 | Out-Null
            Start-Sleep -Seconds 8
            $again = (& $Wsl -d $Distro -u $User -e bash -lc 'systemctl --user is-active --quiet wechat-stack wechat-bot && echo ACTIVE' 2>&1) -join ' '
            Write-Log ('after start: ' + $again.Trim())
        }
    }

    # 3) 健康摘要 + 需要人介入时弹通知
    $health = (& $Wsl -d $Distro -u $User -e bash -lc $Health 2>&1) -join ' '
    Write-Log ('health: ' + $health.Trim())
    $h = $null
    try { $h = $health.Trim() | ConvertFrom-Json } catch { }
    if ($h) {
        $wx = [string]$h.wechat
        $bot = [string]$h.'wechat-bot'
        $hb = 0.0
        try { $hb = [double]$h.heartbeat_age_s } catch { $hb = 0.0 }
        if ($off) {
            # 主动停掉的：下面这些告警全是"该跑却没跑"，此时一条都不该响，
            # 更不能因为心跳停了就自动重启（那正是用户不想要的）
            Reset-HeartbeatStreak
        } elseif ($wx -like 'logged-out*') {
            Alert-Once 'logged_out' '微信掉登录了，年糕.Agent 已暂停' '需要你重新扫码：http://127.0.0.1:6080/vnc.html'
        } elseif ($bot -ne 'active') {
            Alert-Once 'bot_down' '年糕.Agent 服务没起来' ('wechat-bot=' + $bot)
        } elseif (-not $h.stop_file -and $hb -gt 90) {
            # 心跳卡住 = 进程还在但循环不动了。连续两轮都卡才重启（只重启机器人，不碰微信）
            $streak = Step-HeartbeatStreak
            if ($streak -ge 2) {
                Write-Log ('heartbeat stuck ' + $hb + 's streak=' + $streak + ' -> restart wechat-bot')
                & $Wsl -d $Distro -u $User -e bash -lc 'systemctl --user restart wechat-bot' 2>&1 | Out-Null
                Reset-HeartbeatStreak
                Alert-Once 'heartbeat_restart' '年糕.Agent 卡住了，已自动重启' ('heartbeat_age_s=' + $hb + '，连续 ' + $streak + ' 轮无心跳')
            } else {
                Alert-Once 'heartbeat_stale' '年糕.Agent 心跳卡住了' ('heartbeat_age_s=' + $hb + '（再卡一轮就自动重启）')
            }
        } elseif ($h.model -and $h.model.disabled) {
            Reset-HeartbeatStreak
            # 云端模型认证失败会被自动停用（重试只会锁死账号）；这必须让你知道
            Alert-Once 'model_disabled' '年糕.Agent 的云端模型被停用了' (([string]$h.model.provider) + ' ' + ([string]$h.model.model) + '：' + ([string]$h.model.disabled))
        } elseif ($h.model -and $h.model.circuit_open) {
            Alert-Once 'model_circuit' '年糕.Agent 的云端模型连续失败已熔断' (([string]$h.model.provider) + ' ' + ([string]$h.model.last_error))
        } elseif (-not $h.stop_file -and [int]$h.configured_chats -gt 0 -and [int]$h.observed_chats -eq 0) {
            # "活着但瞎了"：进程在跑、心跳正常，可上一轮一个会话都没看成
            Alert-Once 'blind' '年糕.Agent 看不见会话了' '窗口可能被浮层盖住；它每两分钟会自己试一次自救，持续不好请开虚拟屏看一眼'
        } elseif (-not $h.stop_file -and $null -ne $h.moment_draft_age_days -and [double]$h.moment_draft_age_days -ge 7) {
            # 草稿躺着没人审会静默卡住整个朋友圈节奏（有 DRAFT 就不再提新草稿）
            Alert-Once 'draft_stale' '有条朋友圈草稿躺了一周没人审' ('最老的那条已躺 ' + $h.moment_draft_age_days + ' 天；审掉或标 DISCARDED 才会继续提新草稿') 1440
        }
    }
} catch {
    Write-Log ('watchdog error: ' + $_.Exception.Message)
}
