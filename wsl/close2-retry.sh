#!/bin/bash
export DISPLAY=:99
echo "=== 点正确关闭位 (908,50) ==="
xdotool mousemove 908 50 click 1
sleep 1.5
xdotool search --name "^Chat History" 2>/dev/null && echo "STILL_OPEN" || echo "CLOSED"
echo "=== 再试笑脸 (304,602) ==="
xdotool mousemove 304 602 click 1
sleep 2.5
echo "--- 窗口 ---"
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments|Open|Chat*) echo "$w | $n";; esac
done
import -window root /tmp/smile3.png
cp /tmp/smile3.png /mnt/d/AgentPrograms/wechat-bot/wsl/smile-retry2.png
