#!/bin/bash
# 安全重登：只删 login 目录（登录态），不动聊天记录/文件/配置；重启后应弹二维码
export DISPLAY=:0
pkill -9 wechat 2>/dev/null; sleep 1
rm -rf ~/.xwechat/login/* 2>/dev/null
rm -rf ~/.xwechat/lock/* ~/.xwechat/crashinfo/* 2>/dev/null
echo "登录态已清（仅 login 目录）"
nohup /usr/bin/wechat > /tmp/wechat.log 2>&1 &
sleep 4
for i in $(seq 1 15); do
    LINE=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | head -1)
    echo "[$i] $LINE"
    case "$LINE" in
        *280x380*|*281x381*)
            WID=$(echo "$LINE" | grep -oE '0x[0-9a-f]+' | head -1)
            xdotool windowmove --sync "$WID" 1140 610 2>/dev/null
            sleep 1
            import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/wechat-qr.png && echo "QR_READY $WID"
            exit 0;;
    esac
    sleep 2
done
echo "NO_QR_WINDOW"
