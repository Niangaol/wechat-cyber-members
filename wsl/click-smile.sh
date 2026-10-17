#!/bin/bash
export DISPLAY=:99
echo "=== 所有命名窗口 ==="
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  g=$(xdotool getwindowgeometry $w 2>/dev/null | grep Geometry | tr -d ' ')
  [ -n "$n" ] && echo "$w | $n | $g"
done
echo "=== 点笑脸 (304,602) 再看窗口 ==="
timeout 10 xdotool mousemove 304 602
timeout 10 xdotool click 1
sleep 2
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments|Open|*Sticker*|*Emoji*|*sticker*) echo "$w | $n";; esac
done
import -window root /tmp/after-smile.png
cp /tmp/after-smile.png /mnt/d/AgentPrograms/wechat-bot/wsl/after-smile-click.png
