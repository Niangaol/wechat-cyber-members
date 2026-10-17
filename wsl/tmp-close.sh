#!/bin/bash
export DISPLAY=:99
xdotool windowraise 14680150 2>/dev/null
sleep 0.3
# 详情页右上角 X 按钮（窗口 ~540,75 → 绝对 893,189）
xdotool mousemove 893 189
sleep 0.3
xdotool click 1
sleep 1.5
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-detail-closed.png
echo done
