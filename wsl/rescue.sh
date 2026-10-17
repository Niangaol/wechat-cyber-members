#!/bin/bash
# 急救：不管什么烂摊子，强制全套重建（Xvfb→x11vnc→websockify→微信→截图）
unset WAYLAND_DISPLAY
export DISPLAY=:99
export QT_QPA_PLATFORM=xcb

# 杀光（含 systemd 服务，避免它的保活循环跟我抢）
systemctl --user stop wechat-stack 2>/dev/null
pkill -9 -x wechat 2>/dev/null
pkill -9 -f RadiumWMPF 2>/dev/null
pkill -9 -f "x11vnc -display :99" 2>/dev/null
pkill -9 -f "websockify.*6080" 2>/dev/null
pkill -9 -f "Xvfb :99" 2>/dev/null
sleep 3
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null

spawn() { setsid nohup "$@" > /dev/null 2>&1 < /dev/null & disown 2>/dev/null || true; }

spawn Xvfb :99 -screen 0 1280x800x24
sleep 3
xset q > /dev/null 2>&1 && echo XVFB_OK || { echo XVFB_FAIL; exit 1; }
spawn x11vnc -display :99 -localhost -nopw -forever -shared
sleep 2
spawn websockify --web=/usr/share/novnc 127.0.0.1:6080 localhost:5900
sleep 2
ss -tln | grep -q 6080 && echo NOVNC_OK || echo NOVNC_FAIL

rm -rf ~/.xwechat/lock/* ~/.xwechat/crashinfo/* 2>/dev/null
spawn /usr/bin/wechat
sleep 8
WID=$(xwininfo -root -tree 2>/dev/null | grep Weixin | grep -oE '0x[0-9a-f]+' | head -1)
if [ -n "$WID" ]; then
    echo "WECHAT_OK $WID"
    import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/wechat-qr.png && echo SHOT_OK
else
    echo WECHAT_FAIL
    # 微信起不来 → Xvfb 可能有僵尸 selection，重启它再试
    pkill -9 -f "Xvfb :99"; sleep 2; rm -f /tmp/.X99-lock
    spawn Xvfb :99 -screen 0 1280x800x24; sleep 3
    pkill -9 -f "x11vnc -display :99"; sleep 1; spawn x11vnc -display :99 -localhost -nopw -forever -shared; sleep 2
    pkill -9 -f "websockify.*6080"; sleep 1; spawn websockify --web=/usr/share/novnc 127.0.0.1:6080 localhost:5900; sleep 2
    spawn /usr/bin/wechat; sleep 8
    WID=$(xwininfo -root -tree 2>/dev/null | grep Weixin | grep -oE '0x[0-9a-f]+' | head -1)
    [ -n "$WID" ] && { echo "WECHAT_OK2 $WID"; import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/wechat-qr.png && echo SHOT_OK2; } || echo WECHAT_FAIL2
fi
# 完事后把 systemd 服务恢复（它会接管保活）
systemctl --user start wechat-stack 2>/dev/null
echo RESCUE_DONE
