#!/bin/bash
echo "--- 已安装的窗口管理器"
for wm in openbox fluxbox i3 matchbox-window-manager twm metacity xfwm4 mutter jwm icewm; do
  if command -v "$wm" >/dev/null 2>&1; then echo "FOUND $wm -> $(command -v $wm)"; fi
done
echo "--- 正在运行的 WM 进程"
pgrep -a -f "openbox|fluxbox|i3|matchbox|twm|metacity|xfwm|mutter|jwm|icewm" || echo "(none)"
echo "--- Xvfb 进程"
pgrep -a Xvfb || echo "(none)"
