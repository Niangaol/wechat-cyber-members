#!/bin/bash
export DISPLAY=:99
xdotool windowraise 14680150 2>/dev/null
sleep 0.3
# 点头像（窗口 60,365 → 绝对 413,479）
xdotool mousemove 413 479
sleep 0.3
xdotool click 1
sleep 2.0
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-open-avatar.png
# 再滚下来看看别的动态
xdotool mousemove 640 500
sleep 0.2
xdotool click 5
xdotool click 5
sleep 1.5
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-feed-scrolled.png
echo done
