#!/bin/bash
export DISPLAY=:99
echo "=== 所有命名窗口 ==="
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  g=$(xdotool getwindowgeometry $w 2>/dev/null | grep Geometry | tr -d ' ')
  [ -n "$n" ] && echo "$w | $n | $g"
done
echo "=== 全屏截图 ==="
import -window root /tmp/full.png
cp /tmp/full.png /mnt/d/AgentPrograms/wechat-bot/wsl/screen-mention.png
