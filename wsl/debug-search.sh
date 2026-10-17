#!/bin/bash
# 逐步调试搜索切换流程
export DISPLAY=:99
WID=$(xwininfo -root -tree 2>/dev/null | grep '"Weixin"' | grep -oE '0x[0-9a-f]+' | head -1)
xwininfo -id "$WID" > /tmp/w.txt 2>/dev/null
WX=$(grep "Absolute upper-left X" /tmp/w.txt | sed 's/[^0-9]//g')
WY=$(grep "Absolute upper-left Y" /tmp/w.txt | sed 's/[^0-9]//g')
echo "窗口: $WID at $WX,$WY"

# 1. 点搜索框
xdotool mousemove $((WX + 160)) $((WY + 32)) click 1
sleep 1
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/dbg-1-searchbox.png
echo "步骤1 搜索框已点"

# 2. 清空+粘贴
xdotool key --window "$WID" --clearmodifiers ctrl+a
echo "很帅的年糕" | xsel --clipboard --input
xdotool key --window "$WID" --clearmodifiers ctrl+v
sleep 1.5
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/dbg-2-typed.png
echo "步骤2 已输入"

# 3. 点第一项
xdotool mousemove $((WX + 200)) $((WY + 95)) click 1
sleep 2
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/dbg-3-clicked.png
echo "步骤3 已点第一项"
xdotool key --window "$WID" --clearmodifiers Escape
sleep 1
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/dbg-4-final.png
echo "步骤4 Esc 后"
