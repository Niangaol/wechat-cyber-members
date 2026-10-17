#!/bin/bash
# Tab 两次 + Return（激活 Switch Account），紧盯窗口后续变化
export DISPLAY=:0
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
[ -z "$WID" ] && { echo "NO_WINDOW"; exit 1; }
xdotool windowactivate --sync "$WID" 2>/dev/null
sleep 1.5
xdotool key --window "$WID" --clearmodifiers Tab; sleep .8
xdotool key --window "$WID" --clearmodifiers Tab; sleep .8
xdotool key --window "$WID" --clearmodifiers Return
echo "Tab x2 + Return 已发，监视窗口 60 秒"
for i in $(seq 1 20); do
    sleep 3
    LINE=$(xwininfo -root -tree 2>/dev/null | grep '"Weixin"' | head -1)
    echo "[$i] $LINE"
    case "$LINE" in
        *980x710*) echo "MAIN_READY"; MWID=$(echo "$LINE" | grep -oE '0x[0-9a-f]+' | head -1);
                   xdotool windowmove --sync "$MWID" 1140 610 2>/dev/null; sleep 1;
                   import -window "$MWID" /mnt/d/AgentPrograms/wechat-bot/main-ready.png && echo "截图 OK"; exit 0;;
        *280x380*|*281x381*) QWID=$(echo "$LINE" | grep -oE '0x[0-9a-f]+' | head -1);
                   echo "SMALL_WINDOW $QWID"
                   xdotool windowmove --sync "$QWID" 1140 610 2>/dev/null; sleep 1;
                   import -window "$QWID" /mnt/d/AgentPrograms/wechat-bot/login-switch-state.png && echo "截图 OK"; exit 0;;
        "") echo "窗口消失，继续等新窗口";;
    esac
done
echo "TIMEOUT"
