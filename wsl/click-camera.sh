#!/bin/bash
export DISPLAY=:99
W=14680150
echo "--- 点击相机图标 (430,136) ---"
xdotool mousemove 430 136 click 1
sleep 2
import -window $W /tmp/camera-menu.png 2>&1 && echo "shot ok $(stat -c%s /tmp/camera-menu.png)"
cp /tmp/camera-menu.png /mnt/d/AgentPrograms/wechat-bot/wsl/camera-menu.png
echo "--- 是否出现新窗口（文件对话框等） ---"
xdotool search --name ".*" 2>/dev/null | while read -r w; do
  n=$(xdotool getwindowname "$w" 2>/dev/null)
  [ -n "$n" ] && echo "$w | $n"
done
