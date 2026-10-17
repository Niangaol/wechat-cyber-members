#!/bin/bash
export DISPLAY=:99
echo "=== XTEST 点 Open (912,586) ==="
timeout 10 xdotool mousemove 912 586
timeout 10 xdotool click 1
sleep 4
echo "=== 窗口 ==="
for w in $(timeout 10 xdotool search --name ".*" 2>/dev/null); do
  n=$(timeout 5 xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments|Open) echo "$w | $n";; esac
done
import -window root /tmp/after-open.png
cp /tmp/after-open.png /mnt/d/AgentPrograms/wechat-bot/wsl/screen-after-open.png
