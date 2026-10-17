#!/bin/bash
export DISPLAY=:99
xdotool windowraise 14680150 2>/dev/null
sleep 0.3
# 点文字"天知道我经历了什么"（窗口 200,385 → 绝对 553,499）
xdotool mousemove 553 499
sleep 0.3
xdotool click 1
sleep 2.0
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-textclick.png
echo done
