#!/bin/bash
export DISPLAY=:99
echo "=== 1. 点相机图标 (430,136) ==="
timeout 10 xdotool mousemove 430 136
timeout 10 xdotool click 1
sleep 3
DW=$(timeout 10 xdotool search --name "^Open$" 2>/dev/null | head -1)
echo "file dialog: $DW"
if [ -z "$DW" ]; then echo "NO_DIALOG"; exit 1; fi
echo "=== 2. --window 键入路径 ==="
timeout 10 xdotool mousemove --window $DW 323 373
timeout 10 xdotool click --window $DW 1
sleep 0.4
timeout 10 xdotool key --window $DW ctrl+a
sleep 0.3
timeout 20 xdotool type --window $DW "/home/niangao/xwechat_files/moment-test.png"
sleep 0.8
echo "=== 3. --window 点 Open ==="
timeout 10 xdotool mousemove --window $DW 596 373
timeout 10 xdotool click --window $DW 1
sleep 4
echo "=== 4. 窗口状态 ==="
for w in $(timeout 10 xdotool search --name ".*" 2>/dev/null); do
  n=$(timeout 5 xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments|Open) echo "$w | $n";; esac
done
import -window 14680150 /tmp/compose3.png
cp /tmp/compose3.png /mnt/d/AgentPrograms/wechat-bot/wsl/compose-retry.png
echo ok
