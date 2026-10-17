#!/bin/bash
# 账号选择界面点 Log In（292x396 窗口，按钮在中央偏下）
export DISPLAY=:99
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
xwininfo -id "$WID" > /tmp/w.txt 2>/dev/null
WX=$(grep "Absolute upper-left X" /tmp/w.txt | sed 's/[^0-9]//g')
WY=$(grep "Absolute upper-left Y" /tmp/w.txt | sed 's/[^0-9]//g')
echo "窗口 $WID at $WX,$WY"
# Log In 按钮：292 宽窗口中央 x=146，y 约 271（从截图看按钮在 y250-292）
xdotool mousemove $((WX + 146)) $((WY + 271))
sleep 0.3
xdotool click 1
echo "已点击 Log In，等 10 秒"
sleep 10
xwininfo -root -tree 2>/dev/null | grep 'Weixin' | head -2
