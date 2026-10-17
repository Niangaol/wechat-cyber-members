#!/bin/bash
export DISPLAY=:99
DW=$(timeout 10 xdotool search --name "^Open$" 2>/dev/null | head -1)
echo "dialog=$DW"
timeout 10 xdotool mousemove --window $DW 323 373
timeout 10 xdotool click --window $DW 1
sleep 0.4
timeout 10 xdotool key --window $DW ctrl+a
sleep 0.2
timeout 25 xdotool type --window $DW "/home/niangao/xwechat_files/moment-test.png"
sleep 1.2
import -window $DW /tmp/dlg-full.png
cp /tmp/dlg-full.png /mnt/d/AgentPrograms/wechat-bot/wsl/dialog-full-path.png
echo "=== 点 Open (窗口内 596,373) ==="
timeout 10 xdotool mousemove --window $DW 596 373
timeout 10 xdotool click --window $DW 1
sleep 4
for w in $(timeout 10 xdotool search --name ".*" 2>/dev/null); do
  n=$(timeout 5 xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments|Open) echo "$w | $n";; esac
done
import -window root /tmp/after-full.png
cp /tmp/after-full.png /mnt/d/AgentPrograms/wechat-bot/wsl/screen-after-full.png
