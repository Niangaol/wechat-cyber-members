#!/bin/bash
# 等登录窗出现 → 绝对坐标一步式点击 Log In → 等主界面
export DISPLAY=:0

# 等窗口出现（最多 40 秒）
WID=""
for i in $(seq 1 13); do
    WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
    [ -n "$WID" ] && break
    sleep 3
done
[ -z "$WID" ] && { echo "NO_WINDOW"; exit 1; }
echo "登录窗: $WID"

# 挪到可见区
xdotool windowmove --sync "$WID" 1140 610 2>/dev/null
sleep 1
xwininfo -id "$WID" > /tmp/w.txt 2>/dev/null
WX=$(grep "Absolute upper-left X" /tmp/w.txt | sed 's/[^0-9]//g')
WY=$(grep "Absolute upper-left Y" /tmp/w.txt | sed 's/[^0-9]//g')
echo "位置: $WX,$WY"

# 从截图算 Log In 按钮：281x381 窗口，按钮横向 55-226 中心 140，纵向约 250-292 中心 271
BX=$((WX + 140)); BY=$((WY + 271))
echo "按钮坐标: $BX,$BY"
xdotool mousemove "$BX" "$BY"
sleep 0.5
xdotool click 1
echo "已点击"

# 等主界面（980x710）
for i in $(seq 1 25); do
    sleep 3
    INFO=$(xwininfo -root -tree 2>/dev/null | grep '"Weixin"' | head -1)
    W=$(echo "$INFO" | grep -oE '[0-9]+x[0-9]+' | head -1 | cut -dx -f1)
    H=$(echo "$INFO" | grep -oE '[0-9]+x[0-9]+' | head -1 | cut -dx -f2)
    echo "[$i] $W x $H"
    if [ "$W" = "980" ] && [ "$H" = "710" ]; then
        MWID=$(echo "$INFO" | grep -oE '0x[0-9a-f]+' | head -1)
        echo "MAIN_READY $MWID"
        xdotool windowmove --sync "$MWID" 1140 610 2>/dev/null
        sleep 1
        import -window "$MWID" /mnt/d/AgentPrograms/wechat-bot/main-ready.png && echo "截图 OK"
        exit 0
    fi
    # 登录窗也没了但主界面没来 = 可能退了或转圈
    if [ -z "$INFO" ]; then echo "WINDOW_GONE"; fi
done
echo "TIMEOUT"
