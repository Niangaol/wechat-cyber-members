#!/bin/bash
export DISPLAY=:99
xdotool windowraise 14680150 2>/dev/null
sleep 0.3
# 点输入区（窗口 250,480 → 绝对 603,594）
xdotool mousemove 603 594
sleep 0.2
xdotool click 1
sleep 0.5
xdotool type --clearmodifiers "test"
sleep 1.0
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-comment-typed.png
echo done
