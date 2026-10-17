#!/bin/bash
# Tab 一次（焦点移到首个控件=Log In）+ Return
export DISPLAY=:0
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
[ -z "$WID" ] && { echo "NO_WINDOW"; exit 1; }
echo "窗口: $WID"
xdotool windowactivate --sync "$WID" 2>/dev/null
sleep 1.5
xdotool key --window "$WID" --clearmodifiers Tab
sleep 1
xdotool key --window "$WID" --clearmodifiers Return
echo "Tab+Return 已发"
for i in $(seq 1 20); do
    sleep 3
    LINE=$(xwininfo -root -tree 2>/dev/null | grep '"Weixin"' | head -1)
    case "$LINE" in
        *980x710*) MWID=$(echo "$LINE" | grep -oE '0x[0-9a-f]+' | head -1)
                   echo "MAIN_READY $MWID"
                   xdotool windowmove --sync "$MWID" 1140 610 2>/dev/null; sleep 1
                   import -window "$MWID" /mnt/d/AgentPrograms/wechat-bot/main-ready.png && echo "截图 OK"
                   exit 0;;
        "") echo "[$i] 窗口消失";;
        *) echo "[$i] 仍登录窗";;
    esac
done
import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/login-tab1-state.png 2>/dev/null && echo "状态截图 OK"
echo "TIMEOUT"
