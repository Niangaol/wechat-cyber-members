#!/bin/bash
# 纯键盘登录：activate 后直接 Return（不 Tab，默认焦点应在 Log In）
export DISPLAY=:0
WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
[ -z "$WID" ] && { echo "NO_WINDOW"; exit 1; }
echo "窗口: $WID"
xdotool windowactivate --sync "$WID" 2>/dev/null
sleep 1.5
xdotool key --window "$WID" --clearmodifiers Return
echo "Return 已发送，轮询主界面"
for i in $(seq 1 30); do
    sleep 3
    LINE=$(xwininfo -root -tree 2>/dev/null | grep '"Weixin"' | head -1)
    case "$LINE" in
        *980x710*) echo "MAIN_READY"; MWID=$(echo "$LINE" | grep -oE '0x[0-9a-f]+' | head -1);
                   xdotool windowmove --sync "$MWID" 1140 610 2>/dev/null; sleep 1;
                   import -window "$MWID" /mnt/d/AgentPrograms/wechat-bot/main-ready.png && echo "截图 OK"; exit 0;;
        "") echo "[$i] 窗口消失";;
        *) echo "[$i] $LINE";;
    esac
done
echo "TIMEOUT"
