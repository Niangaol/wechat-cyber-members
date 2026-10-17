#!/bin/bash
export DISPLAY=:99
xdotool windowraise 14680150 2>/dev/null
sleep 0.3
xdotool mousemove 883 632
sleep 0.3
xdotool click 1
sleep 1.5
import -window root /mnt/d/AgentPrograms/wechat-bot/wsl/cal-more-menu.png
echo "--- 新窗口 ---"
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  g=$(xwininfo -id $w 2>/dev/null | grep "Absolute upper-left" | head -1)
  [ -n "$n" ] && echo "$w | $n | $g"
done
echo done
