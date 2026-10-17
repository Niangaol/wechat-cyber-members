#!/bin/bash
export DISPLAY=:99
echo "=== 1. 点相机图标 ==="
timeout 10 xdotool mousemove 430 136
timeout 10 xdotool click 1
sleep 3
DW=$(timeout 10 xdotool search --name "^Open$" 2>/dev/null | head -1)
echo "dialog=$DW"
[ -z "$DW" ] && { echo NO_DIALOG; exit 1; }
echo "=== 2. 键入完整路径 ==="
timeout 10 xdotool mousemove --window $DW 323 373
timeout 10 xdotool click --window $DW 1
sleep 0.4
timeout 10 xdotool key --window $DW ctrl+a
sleep 0.2
timeout 25 xdotool type --window $DW "/home/niangao/xwechat_files/moment-test.png"
sleep 0.8
echo "=== 3. XTEST 按 Enter（不用 --window）==="
timeout 10 xdotool key Return
sleep 5
for w in $(timeout 10 xdotool search --name ".*" 2>/dev/null); do
  n=$(timeout 5 xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments|Open) echo "$w | $n";; esac
done
import -window root /tmp/enter2.png
cp /tmp/enter2.png /mnt/d/AgentPrograms/wechat-bot/wsl/screen-enter2.png
