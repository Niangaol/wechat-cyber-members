#!/bin/bash
# 激活微信窗口 + 挪到屏幕中央 + 截二维码
export DISPLAY=:0

# 找最新 Weixin 窗口 ID
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
echo "Weixin 窗口 ID: $WID"

if [ -z "$WID" ]; then
    echo "找不到 Weixin 窗口，微信还在跑吗："
    pgrep -c -f RadiumWMPF
    exit 1
fi

echo "=== 窗口状态 ==="
xwininfo -id "$WID" | grep -E "Map State|Width|Height|Absolute"

echo "=== 激活 + 居中 ==="
xdotool windowactivate "$WID" && echo "activate OK"
xdotool windowmove "$WID" 1140 610 && echo "move OK"
sleep 1

echo "=== 截图 ==="
import -window "$WID" /tmp/wechat-qr.png && echo "截图 OK"
ls -lh /tmp/wechat-qr.png
cp /tmp/wechat-qr.png /mnt/d/AgentPrograms/wechat-bot/wechat-qr.png && echo "已复制到 D 盘"
