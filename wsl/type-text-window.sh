#!/bin/bash
export DISPLAY=:99
MW=14680150
printf '%s' "$(cat /tmp/moment-text.txt)" | xsel --clipboard --input
echo "--- --window 点击输入框（窗口内 285,53）---"
timeout 10 xdotool mousemove --window $MW 285 53
timeout 10 xdotool click --window $MW 1
sleep 0.6
echo "--- --window ctrl+v ---"
timeout 10 xdotool key --window $MW ctrl+v
sleep 1.2
import -window $MW /tmp/compose-typed2.png
cp /tmp/compose-typed2.png /mnt/d/AgentPrograms/wechat-bot/wsl/compose-typed2.png
echo "ok"
