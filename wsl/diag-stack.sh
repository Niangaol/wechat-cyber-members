#!/bin/bash
unset WAYLAND_DISPLAY
export DISPLAY=:99
echo "=== 进程 ==="
pgrep -a Xvfb | head -2; pgrep -a x11vnc | head -2; pgrep -a websockify | head -2
echo "=== X 服务器 ==="
xset q > /dev/null 2>&1 && echo XVFB_OK || echo XVFB_FAIL
echo "=== 微信主进程 ==="
pgrep -a -x wechat | head -3 || echo "无 wechat 主进程"
echo "=== 手动前台起微信（5秒） ==="
timeout 5 /usr/bin/wechat 2>&1 | head -15
echo "=== 退出码: $? ==="
