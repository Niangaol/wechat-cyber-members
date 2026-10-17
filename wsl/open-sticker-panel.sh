#!/bin/bash
export DISPLAY=:99
W=14680080
run() { timeout 12 "$@" || echo "TIMEOUT: $*"; }
echo "=== 点工具栏表情图标（笑脸，绝对约 300,600）==="
run xdotool mousemove 300 600
run xdotool click 1
sleep 2
import -window $W /tmp/sticker-panel.png
cp /tmp/sticker-panel.png /mnt/d/AgentPrograms/wechat-bot/wsl/sticker-panel.png
echo "=== 全屏看面板 ==="
import -window root /tmp/sticker-root.png
cp /tmp/sticker-root.png /mnt/d/AgentPrograms/wechat-bot/wsl/sticker-root.png
echo ok
