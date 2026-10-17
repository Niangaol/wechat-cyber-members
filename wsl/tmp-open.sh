#!/bin/bash
export DISPLAY=:99
xdotool windowraise 14680150 2>/dev/null
sleep 0.3
# 点第一条动态的文字区（窗口相对 200,385 → 绝对 553,499）
xdotool mousemove 553 499
sleep 0.3
xdotool click 1
sleep 2.0
echo "--- 窗口 ---"
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  g=$(xwininfo -id $w 2>/dev/null | grep "Absolute upper-left" | head -1)
  [ -n "$n" ] && echo "$w | $n | $g"
done
import -window root /mnt/d/AgentPrograms/wechat-bot/wsl/cal-after-open.png
echo done
