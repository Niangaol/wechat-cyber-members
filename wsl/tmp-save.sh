#!/bin/bash
export DISPLAY=:99
# 确保 Moments 窗口置顶（对话框是它的子窗口）
xdotool windowraise 14680150 2>/dev/null
sleep 0.3
xdotool mousemove 576 425
sleep 0.3
xdotool click 1
sleep 2.5
echo "--- 窗口列表 ---"
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  case "$n" in Moments|Open|wechat|WeChat) echo "$w | $n";; esac
done
import -window 14680150 /mnt/d/AgentPrograms/wechat-bot/wsl/cal-after-save.png
echo done
