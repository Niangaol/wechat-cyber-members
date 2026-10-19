# Windows 一键启停

桌面文件夹「微信机器人启停」里三个文件，双击即用：

| 文件 | 作用 |
| --- | --- |
| `启动机器人.cmd` | 启动机器人（不受早 8 晚 10 限制，点了就是想现在跑） |
| `停止机器人.cmd` | 停止机器人；微信本体继续开着，下次启动是秒起 |
| `查看状态.cmd` | 机器人/微信栈/排班定时器/健康值一览 |

## 实现方式

三个 `.cmd` 只做一件事：调 `wsl/botctl.sh`。业务逻辑全在那一个文件里，
别处不要再复制一份（改行为只改 botctl.sh）。

```
wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc "sh /mnt/d/AgentPrograms/wechat-bot/wsl/botctl.sh start"
```

在 WSL 里也可以直接用：

```bash
sh wsl/botctl.sh start|stop|status
```

## 和原来排班的关系

2026-10-19 之前是 systemd 定时器自动排班（每天 08:00 起、22:00 停，
`bot-schedule.sh` + 两个 timer）。用户要求改为手动控制后，两个定时器已
`disable`，所以停掉就是真停掉，不会明天 08:00 自己活过来。

想恢复自动排班：

```bash
systemctl --user enable --now wechat-bot-start.timer wechat-bot-stop.timer
```

注意 `config/resident.json` 里的 `online_window`（早 8 晚 10 的进程内闸门）
是另一层兜底，和定时器是两回事：手动启动不受它限制，但进程内闸门仍会在
22:00 后让机器人下班。要 24 小时手动跑，把 `online_window.enabled` 改 false。

## 编码注意事项

`.cmd` 里 `rem` 注释必须是 ASCII。cmd.exe 对 UTF-8 批处理的解析不老实，
中文注释（尤其含 `——` 的行）会被当成命令执行并报一串乱码错误；
`chcp 65001` 也要放在文件最前面。中文只放在 `chcp` 之后的 `echo` 里，
实测正常。
