#!/bin/bash
export DISPLAY=:99
# 先分析绿色 Send 位置（在 python 里做），这里先清空
xdotool key --clearmodifiers ctrl+a
sleep 0.3
xdotool key --clearmodifiers Delete
sleep 0.5
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-comment-cleared.png
xdotool key Escape
sleep 1.0
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-comment-escaped.png
echo done
