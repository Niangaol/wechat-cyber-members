#!/bin/bash
export DISPLAY=:99
# 2. 点输入框 (638,169) → 剪贴板粘贴文案
printf '%s' "$(cat /tmp/moment-text.txt)" | xsel --clipboard --input
echo "clipboard: [$(xsel --clipboard --output | head -c 50)...]"
xdotool mousemove 638 169 click 1
sleep 0.6
xdotool key ctrl+v
sleep 1.0
echo "=== 截图确认 ==="
import -window 14680150 /tmp/compose-typed.png
cp /tmp/compose-typed.png /mnt/d/AgentPrograms/wechat-bot/wsl/compose-typed.png
echo "ok"
