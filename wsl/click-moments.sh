#!/bin/bash
# 点击左侧边栏的"朋友圈"图标并截图验证
# 边栏布局（980x710 主界面）：头像 y~45，功能图标间距 45：聊天112/通讯录157/收藏202/朋友圈247/视频号292
export DISPLAY=:0

WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
echo "窗口 ID: $WID"
xwininfo -id "$WID" > /tmp/winfo.txt 2>/dev/null
WX=$(grep "Absolute upper-left X" /tmp/winfo.txt | sed 's/[^0-9]//g')
WY=$(grep "Absolute upper-left Y" /tmp/winfo.txt | sed 's/[^0-9]//g')
WW=$(grep "Width:" /tmp/winfo.txt | sed 's/[^0-9]//g')
WH=$(grep "Height:" /tmp/winfo.txt | sed 's/[^0-9]//g')
echo "窗口: $WX,$WY $WW x $WH"

xdotool windowactivate "$WID" 2>/dev/null
sleep 0.5

# 朋友圈图标（边栏第 4 个功能图标）
ICON_X=$((WX + 33))
ICON_Y=$((WY + 247))
echo "点击朋友圈图标: $ICON_X,$ICON_Y"
xdotool mousemove "$ICON_X" "$ICON_Y" click 1
sleep 2

import -window "$WID" /tmp/wechat-moments.png && echo "截图 OK"
cp /tmp/wechat-moments.png /mnt/d/AgentPrograms/wechat-bot/wechat-moments.png
