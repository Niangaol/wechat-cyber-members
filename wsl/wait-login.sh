#!/bin/bash
# 登录检测器：轮询 Weixin 窗口尺寸，登录窗(280x380) -> 主界面(大窗) 即视为登录成功
export DISPLAY=:0

for i in $(seq 1 30); do
    WID=$(xwininfo -root -tree 2>/dev/null | grep 'Weixin' | grep -oE '0x[0-9a-f]+' | head -1)
    W=0
    H=0
    if [ -n "$WID" ]; then
        W=$(xwininfo -id "$WID" 2>/dev/null | grep "Width:" | grep -oE "[0-9]+" | head -1)
        H=$(xwininfo -id "$WID" 2>/dev/null | grep "Height:" | grep -oE "[0-9]+" | head -1)
        echo "[$i/30] 窗口 $W x $H"
        if [ "$W" -gt 600 ] 2>/dev/null; then
            echo "LOGIN_DETECTED 窗口变成主界面了！"
            import -window "$WID" /tmp/wechat-main.png && echo "主界面截图 OK"
            cp /tmp/wechat-main.png /mnt/d/AgentPrograms/wechat-bot/wechat-main.png
            echo "=== ~/.xwechat 目录 ==="
            ls ~/.xwechat/ 2>/dev/null
            echo "=== SQLite 数据库侦查（WAL 路线） ==="
            find ~/.xwechat ~/xwechat_files -name "*.db" 2>/dev/null | head -8
            exit 0
        fi
    else
        echo "[$i/30] 没看到 Weixin 窗口"
    fi
    sleep 3
done
echo "TIMEOUT 90 秒内没检测到登录"
exit 2
