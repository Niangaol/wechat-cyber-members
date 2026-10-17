#!/bin/bash
# 关闭登录后的"版本更新说明"弹窗，露出主界面
export DISPLAY=:0

WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
echo "窗口 ID: $WID"

xwininfo -id "$WID" > /tmp/winfo.txt 2>/dev/null
WX=$(grep "Absolute upper-left X" /tmp/winfo.txt | sed 's/[^0-9]//g')
WY=$(grep "Absolute upper-left Y" /tmp/winfo.txt | sed 's/[^0-9]//g')
WW=$(grep "Width:" /tmp/winfo.txt | sed 's/[^0-9]//g')
WH=$(grep "Height:" /tmp/winfo.txt | sed 's/[^0-9]//g')
echo "位置: $WX,$WY 尺寸: $WW x $WH"

xdotool windowactivate "$WID" 2>/dev/null

# 尝试 1: Escape 关弹窗
xdotool key Escape
sleep 1

NEWW=$(xwininfo -id "$WID" 2>/dev/null | grep "Width:" | sed 's/[^0-9]//g')
if [ -z "$NEWW" ] || [ "$NEWW" != "$WW" ]; then
    echo "ESCAPE_CLOSED 弹窗已关"
else
    CLOSE_X=$((WX + WW - 25))
    CLOSE_Y=$((WY + 22))
    echo "弹窗还在，点右上角 × 坐标: $CLOSE_X,$CLOSE_Y"
    xdotool mousemove "$CLOSE_X" "$CLOSE_Y" click 1
    sleep 1
    echo "已点 ×"
fi

sleep 1
import -window "$WID" /tmp/wechat-main.png && echo "截图 OK"
cp /tmp/wechat-main.png /mnt/d/AgentPrograms/wechat-bot/wechat-main.png
