#!/bin/bash
export DISPLAY=:99
xdotool windowraise 14680150 2>/dev/null
sleep 0.3
xdotool mousemove 794 668
sleep 0.3
xdotool click 1
sleep 1.8
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-comment-box.png
import -window root /mnt/d/AgentPrograms/wechat-bot/wsl/cal-comment-box-root.png
echo "--- 窗口 ---"
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  g=$(xwininfo -id $w 2>/dev/null | grep "Absolute upper-left" | head -1)
  [ -n "$n" ] && echo "$w | $n | $g"
done
echo done
