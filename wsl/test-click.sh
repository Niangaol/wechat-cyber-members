#!/bin/bash
# 测试 XTest 点击是否生效：点会话列表"很帅的年糕"（应打开聊天窗口）
export DISPLAY=:0

WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
echo "窗口 ID: $WID"

xwininfo -id "$WID" > /tmp/w1.txt 2>/dev/null
WX=$(grep "Absolute upper-left X" /tmp/w1.txt | sed 's/[^0-9]//g')
WY=$(grep "Absolute upper-left Y" /tmp/w1.txt | sed 's/[^0-9]//g')
echo "activate 前位置: $WX,$WY"

xdotool windowactivate "$WID" 2>/dev/null
sleep 1

xwininfo -id "$WID" > /tmp/w2.txt 2>/dev/null
WX2=$(grep "Absolute upper-left X" /tmp/w2.txt | sed 's/[^0-9]//g')
WY2=$(grep "Absolute upper-left Y" /tmp/w2.txt | sed 's/[^0-9]//g')
echo "activate 后位置: $WX2,$WY2"

# 点会话项"很帅的年糕"（会话列表在边栏右侧，相对坐标约 x=250 y=270）
CLICK_X=$((WX2 + 250))
CLICK_Y=$((WY2 + 270))
echo "点击会话项: $CLICK_X,$CLICK_Y"
xdotool mousemove "$CLICK_X" "$CLICK_Y"
sleep 0.3
xdotool click 1
sleep 2

import -window "$WID" /tmp/wechat-test.png && echo "截图 OK"
cp /tmp/wechat-test.png /mnt/d/AgentPrograms/wechat-bot/wechat-test.png
