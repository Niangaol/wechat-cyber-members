#!/bin/bash
# 微信起到 xpra :100（软件渲染，绕开 xpra 的 GL 兼容问题）
unset WAYLAND_DISPLAY
export DISPLAY=:100
export QT_QPA_PLATFORM=xcb
export LIBGL_ALWAYS_SOFTWARE=1
export QT_XCB_GL_INTEGRATION=none
export QTWEBENGINE_DISABLE_SANDBOX=1

pkill -9 -x wechat 2>/dev/null
pkill -9 -f RadiumWMPF 2>/dev/null
sleep 2
rm -rf ~/.xwechat/lock/* ~/.xwechat/crashinfo/* 2>/dev/null
setsid nohup /usr/bin/wechat > /tmp/wechat-xpra.log 2>&1 < /dev/null &
disown 2>/dev/null
sleep 10
WID=$(xwininfo -root -tree 2>/dev/null | grep Weixin | grep -oE '0x[0-9a-f]+' | head -1)
if [ -n "$WID" ]; then
    echo "WECHAT_ON_XPRA $WID"
    xwininfo -id "$WID" 2>/dev/null | grep -E "Width|Height|Map"
else
    echo "WECHAT_FAIL"
    pgrep -f RadiumWMPF | wc -l
fi
