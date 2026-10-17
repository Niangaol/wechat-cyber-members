#!/bin/bash
# 在全新 WSL 里恢复三个常驻服务（幂等：重复跑就是覆盖+重启）
#   用法：bash wsl/install-services.sh
set -eu
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/.config/systemd/user"
mkdir -p "$DEST"
for unit in wechat-stack wechat-bot wechat-soak; do
    src="$HERE/$unit.service"
    if [ ! -f "$src" ]; then
        echo "缺少 $src" >&2
        exit 1
    fi
    cp "$src" "$DEST/$unit.service"
    echo "已安装 $unit.service"
done
systemctl --user daemon-reload
loginctl enable-linger "$(id -un)" >/dev/null 2>&1 || true
# 默认只动机器人和烤机：**重启 wechat-stack 会重新拉起微信客户端**，
# 而客户端起来后可能需要"手机确认登录"（2026-10-17 凌晨我就这么把机器人按停了 ✗）。
# 真要重启客户端请显式加 --with-stack，并且人在场。
WANT_STACK=0
[ "${1:-}" = "--with-stack" ] && WANT_STACK=1
for unit in wechat-stack wechat-bot wechat-soak; do
    systemctl --user enable "$unit" >/dev/null
    if [ "$unit" = "wechat-stack" ] && [ "$WANT_STACK" = "0" ]; then
        systemctl --user is-active --quiet wechat-stack || systemctl --user start wechat-stack
        continue
    fi
    systemctl --user restart "$unit"
done
sleep 3
for unit in wechat-stack wechat-bot wechat-soak; do
    printf '%-14s %s / %s\n' "$unit" "$(systemctl --user is-active "$unit")" "$(systemctl --user is-enabled "$unit")"
done
