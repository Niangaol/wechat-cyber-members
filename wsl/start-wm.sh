#!/bin/bash
# 启动 openbox（Xvfb 必须有 WM，否则窗口激活/点击不可靠）
export DISPLAY=:99
unset WAYLAND_DISPLAY
if ! pgrep -x openbox >/dev/null; then
  setsid nohup openbox --sm-disable >/dev/null 2>&1 </dev/null &
  sleep 2
  echo "openbox started"
else
  echo "openbox already running"
fi
pgrep -a openbox || echo "(not running)"
echo "--- 验证窗口激活能力"
xdotool windowactivate --sync 0xc0002d 2>&1 | head -2 || true
