#!/bin/bash
export DISPLAY=:99
W=14680080
run() { timeout 12 "$@" || echo "TIMEOUT: $*"; }
echo "=== 右键图片预览 ==="
run xdotool mousemove 600 625
run xdotool click 3
sleep 1.2
import -window $W /tmp/rclick.png
cp /tmp/rclick.png /mnt/d/AgentPrograms/wechat-bot/wsl/rclick-menu.png
echo "=== 全屏看有无菜单弹出 ==="
import -window root /tmp/rclick-root.png
cp /tmp/rclick-root.png /mnt/d/AgentPrograms/wechat-bot/wsl/rclick-root.png
