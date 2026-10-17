#!/bin/bash
# 点 Network proxy settings 左上角 < 返回箭头退出面板
export DISPLAY=:99
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
xwininfo -id "$WID" > /tmp/w.txt 2>/dev/null
WX=$(grep "Absolute upper-left X" /tmp/w.txt | sed 's/[^0-9]//g')
WY=$(grep "Absolute upper-left Y" /tmp/w.txt | sed 's/[^0-9]//g')
echo "窗口 $WID at $WX,$WY"
# < 箭头在面板左上：窗口 292x396，面板几乎占满，< 约在 (30, 30) 相对
xdotool mousemove $((WX + 30)) $((WY + 32))
sleep 0.3
xdotool click 1
sleep 2
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/panel-back.png 2>/dev/null && echo SHOT_OK
xwininfo -id "$WID" 2>/dev/null | grep -E "Width|Height"
