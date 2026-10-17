#!/bin/bash
export DISPLAY=:99
echo "=== 1. 点相机图标 ==="
timeout 10 xdotool mousemove 430 136
timeout 10 xdotool click 1
sleep 3
DW=$(timeout 10 xdotool search --name "^Open$" 2>/dev/null | head -1)
echo "dialog=$DW"
[ -z "$DW" ] && { echo NO_DIALOG; exit 1; }
echo "=== 2. 点选 moment-test.png 那一行（蓝色高亮项，窗口内约 300,220）==="
timeout 10 xdotool mousemove --window $DW 300 220
timeout 10 xdotool click --window $DW 1
sleep 1.0
echo "=== 3. --window 按 Enter 确认 ==="
timeout 10 xdotool key --window $DW Return
sleep 4
echo "=== 4. 窗口与截图 ==="
for w in $(timeout 10 xdotool search --name ".*" 2>/dev/null); do
  n=$(timeout 5 xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments|Open) echo "$w | $n";; esac
done
import -window root /tmp/enter-try.png
cp /tmp/enter-try.png /mnt/d/AgentPrograms/wechat-bot/wsl/screen-enter.png
