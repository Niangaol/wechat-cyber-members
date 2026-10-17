#!/bin/bash
# xpra setsid 后台驻留（bash -lc 退出不会带走）
unset WAYLAND_DISPLAY
pkill -9 xpra 2>/dev/null; sleep 2
rm -rf /tmp/.xpra* 2>/dev/null

setsid nohup xpra start :100 --bind-tcp=0.0.0.0:10001 --no-daemon > /tmp/xpra.log 2>&1 < /dev/null &
disown 2>/dev/null
sleep 8
echo "=== xpra 会话 ==="
xpra list 2>&1
echo "=== 端口 ==="
ss -tln | grep 10001 | head -1 || echo "10001 未监听"
echo "=== 日志尾 ==="
tail -5 /tmp/xpra.log
