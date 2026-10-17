#!/bin/bash
export DISPLAY=:99
xdotool mousemove 145 282 click 1
sleep 4
echo "--- 窗口 ---"
xdotool search --name ".*" 2>/dev/null | while read -r w; do
  n=$(xdotool getwindowname "$w" 2>/dev/null)
  g=$(xdotool getwindowgeometry "$w" 2>/dev/null | tr '\n' ' ')
  [ -n "$n" ] && echo "$w | $n | $g"
done
echo "--- 标定 ---"
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/calibrate-moments-window.py
