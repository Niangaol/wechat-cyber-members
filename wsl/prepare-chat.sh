#!/bin/bash
# 找微信主窗口→移到可见区→打开「很帅的年糕」会话→截图
export DISPLAY=:0
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
[ -z "$WID" ] && { echo "NO_WINDOW"; exit 1; }
echo "窗口: $WID"
xwininfo -id "$WID" > /tmp/w.txt 2>/dev/null
WX=$(grep "Absolute upper-left X" /tmp/w.txt | sed 's/[^0-9]//g')
WY=$(grep "Absolute upper-left Y" /tmp/w.txt | sed 's/[^0-9]//g')
WW=$(grep "Width:" /tmp/w.txt | sed 's/[^0-9]//g')
WH=$(grep "Height:" /tmp/w.txt | sed 's/[^0-9]//g')
echo "位置: $WX,$WY 尺寸: $WW x $WH"
xdotool windowactivate --sync "$WID" 2>/dev/null
xdotool windowmove --sync "$WID" 1140 610 2>/dev/null
sleep 1
# 点会话列表里的「很帅的年糕」（会话项在边栏右侧，相对坐标约 250,270）
xdotool mousemove --window "$WID" 250 270 click 1 2>/dev/null || xdotool mousemove 1390 880 click 1
sleep 2
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/sticker-step1.png && echo "截图 OK"
