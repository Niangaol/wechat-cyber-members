#!/usr/bin/env bash
# QQ 侧一键安装（幂等，可重复跑）。只做"准备运行环境"这一件事：
#   1) 建 QQ 专用 venv（~/.local/share/qq-bot/venv）并安装 qq/requirements.txt
#   2) 建状态目录（~/.local/state/qq-bot，700）与配置目录（~/.config/qq-bot，700）
#   3) 生成 qq.env（随机 token，600）、qq.json（从 qq/config/qq.example.json 复制，600）、napcat.env 模板
#   4) 把 wsl/qq-bot.service、wsl/qq-napcat.service 拷到 ~/.config/systemd/user/ 并 daemon-reload
# 明确【不做】的事（想清楚再改，这几条是安全边界）：
#   - 不启动、不 enable 任何服务；微信的 wechat-* 服务一行都不碰（不动、不重启、不停）
#   - 不碰 NapCat 的安装目录与配置（本机 NapCat 在 ~/Napcat，rootless，不归本脚本管）
#   - 不 sudo、不装系统包、不装 NapCat、不写 NapCat 的配置
#   - 不写 ~/.local/state/wechat-bot/ 里的任何东西
# 用法：
#   bash wsl/install-qq.sh                 # 正常安装
#   bash wsl/install-qq.sh --dry-run       # 只打印将要做的事，一个文件都不写
#   bash wsl/install-qq.sh --skip-deps     # 跳过 pip（离线自检用；venv 目录仍会创建）
#   bash wsl/install-qq.sh --no-units      # 不安装 systemd 单元
#   bash wsl/install-qq.sh --help
# 完整部署手册（含 NapCat 安装、扫码、分阶段上线）见 docs/QQ.md。
set -euo pipefail
umask 077

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

SHARE="$HOME/.local/share/qq-bot"
VENV="$SHARE/venv"
STATE="$HOME/.local/state/qq-bot"
CONF="$HOME/.config/qq-bot"
UNIT_DEST="$HOME/.config/systemd/user"
ENV_FILE="$CONF/qq.env"
NAP_ENV="$CONF/napcat.env"
CFG_FILE="$CONF/qq.json"
EXAMPLE="$REPO/qq/config/qq.example.json"
REQS="$REPO/qq/requirements.txt"
PORT=18080

DRY=0        # 1 = dry-run
DEPS=1       # 0 = 跳过 pip
UNITS=1      # 0 = 不装 systemd 单元

log()  { printf '[qq-install] %s\n' "$*"; }
step() { printf '\n==== %s ====\n' "$*"; }
warn() { printf '[qq-install][警告] %s\n' "$*" >&2; }
die()  { printf '[qq-install][失败] %s\n' "$*" >&2; exit 1; }

usage() {
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)   DRY=1 ;;
        --skip-deps) DEPS=0 ;;
        --no-units)  UNITS=0 ;;
        -h|--help)   usage ;;
        *)           die "未知参数 $1（--help 看用法）" ;;
    esac
    shift
done

# 真跑就执行，dry-run 只打印
run() {
    if [ "$DRY" = "1" ]; then
        printf '  [dry-run] %s\n' "$*"
    else
        "$@"
    fi
}

step "0/7 环境与前置检查"
[ -d "$REPO/qq" ] || die "仓库里没有 qq/ 目录，当前 REPO=$REPO（请从仓库根调用本脚本）"
[ -f "$REQS" ] || die "缺少 $REQS —— 依赖清单是必需项（qq-nonebot 负责提供）；补齐后再跑本脚本"
command -v python3 >/dev/null 2>&1 || die "找不到 python3"
PY_OK="$(python3 -c 'import sys; print(1 if sys.version_info >= (3,10) else 0)')"
[ "$PY_OK" = "1" ] || die "python3 版本过低：$(python3 -V)（NoneBot2 需要 3.10+）"
python3 -c 'import venv' 2>/dev/null || die "python3 缺少 venv 模块（需要 python3-venv）"
log "python3 = $(python3 -V 2>&1) · 仓库根 = $REPO"
[ -f "$REPO/qq/bot.py" ] || warn "还没看到 qq/bot.py（qq-nonebot 的交付物），服务现在起不来，属预期"
if [ "$DEPS" = "1" ]; then
    log "将创建/复用 venv：$VENV（Python 3.10+）"
else
    log "--skip-deps：跳过 pip（不动依赖，只准备目录与配置）"
fi

step "1/7 目录（全部 700，只有本用户可读写）"
run mkdir -p "$SHARE" "$STATE" "$CONF" "$UNIT_DEST"
run chmod 700 "$SHARE" "$STATE" "$CONF"
log "状态目录 $STATE"
log "配置目录 $CONF"

step "2/7 QQ 专用 venv"
if [ "$DRY" = "1" ]; then
    log "[dry-run] python3 -m venv $VENV（已存在则跳过）"
elif [ -x "$VENV/bin/python" ]; then
    log "venv 已存在，复用：$("$VENV/bin/python" -V 2>&1)"
else
    log "创建 venv：$VENV"
    python3 -m venv "$VENV" || die "创建 venv 失败（检查磁盘与 python3-venv）"
    [ -x "$VENV/bin/python" ] || die "venv 建好了但没有 $VENV/bin/python，环境异常"
fi

step "3/7 安装依赖（pip install -r qq/requirements.txt）"
if [ "$DEPS" = "0" ]; then
    log "按参数要求跳过 pip"
elif [ "$DRY" = "1" ]; then
    log "[dry-run] $VENV/bin/python -m pip install --upgrade pip"
    log "[dry-run] $VENV/bin/python -m pip install -r $REQS"
else
    log "升级 pip（幂等）"
    "$VENV/bin/python" -m pip install --quiet --upgrade pip || warn "pip 自升级失败，继续（不影响后续安装）"
    log "安装 qq/requirements.txt（需要能访问 pypi）"
    "$VENV/bin/python" -m pip install -r "$REQS" || die "pip 安装依赖失败，见上面的报错"
    log "依赖安装完成"
fi
if [ "$DRY" = "0" ] && [ "$DEPS" = "1" ] && [ -x "$VENV/bin/python" ]; then
    "$VENV/bin/python" -c 'import nonebot' 2>/dev/null \
        || warn "venv 里 import nonebot 失败：确认 qq/requirements.txt 含 nonebot2 与 onebot 适配器"
fi

step "4/7 环境变量文件 qq.env（600，含随机 token）"
if [ "$DRY" = "1" ]; then
    log "[dry-run] 若 $ENV_FILE 不存在则生成（QQ_BOT_PORT/QQ_BOT_ONEBOT_TOKEN/QQ_BOT_CONFIG）"
elif [ -f "$ENV_FILE" ]; then
    log "已存在，保持不动（幂等）：$ENV_FILE"
    for key in QQ_BOT_PORT QQ_BOT_ONEBOT_TOKEN QQ_BOT_CONFIG; do
        grep -q "^$key=" "$ENV_FILE" || warn "$ENV_FILE 里缺 $key（服务可能起不来）"
    done
else
    TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    cat > "$ENV_FILE" <<ENVEOF
# QQ 机器人运行环境变量（600 权限，绝不进仓库）。由 wsl/install-qq.sh 生成，可手工修改。
# 改完执行：systemctl --user restart qq-bot  （只重启 QQ，不碰微信）
# QQ_BOT_ONEBOT_TOKEN 必须与 NapCat 里"WebSocket 客户端"的 token 完全一致，否则 NapCat 连过来会被 403 拒绝。
QQ_BOT_PORT=$PORT
QQ_BOT_ONEBOT_TOKEN=$TOKEN
QQ_BOT_CONFIG=$CFG_FILE
ENVEOF
    chmod 600 "$ENV_FILE"
    log "已生成 $ENV_FILE（token 随机，不打印明文）"
fi

step "5/7 配置文件 qq.json（600）"
if [ "$DRY" = "1" ]; then
    log "[dry-run] 若 $CFG_FILE 不存在则从 qq/config/qq.example.json 复制"
elif [ -f "$CFG_FILE" ]; then
    log "已存在，保持不动（幂等）：$CFG_FILE"
elif [ -f "$EXAMPLE" ]; then
    cp "$EXAMPLE" "$CFG_FILE"
    chmod 600 "$CFG_FILE"
    log "已从示例复制：$CFG_FILE"
    warn "示例里 auto_send=false、groups 为空：这是有意为之，先别急着放开（见 docs/QQ.md 的分阶段闸门）"
else
    warn "既没有 $CFG_FILE 也没有示例 $EXAMPLE（qq-nonebot 的交付物），跳过"
    warn "补齐后手工执行：cp $EXAMPLE $CFG_FILE && chmod 600 $CFG_FILE"
fi

step "6/7 NapCat 侧环境文件模板（可选）"
if [ "$DRY" = "1" ]; then
    log "[dry-run] 若 $NAP_ENV 不存在则生成模板"
elif [ -f "$NAP_ENV" ]; then
    log "已存在，保持不动（幂等）：$NAP_ENV"
else
    cat > "$NAP_ENV" <<'NAPEOF'
# NapCat（QQ NT 客户端）的可选环境文件，供 wsl/qq-napcat.service 读取。
# 只放代理/证书变量，或下面的快速登录参数。QQ 号不能进仓库，所以只写在这个 600 文件里。
# 快速登录（免扫码，等价于启动时加 -q 参数）：取消下面一行注释并换成你的 QQ 号
#QQ_BOT_QQ_ARGS=-q 123456789
NAPEOF
    chmod 600 "$NAP_ENV"
    log "已生成 $NAP_ENV"
fi

step "7/7 systemd 用户单元（只安装，不 enable、不启动）"
if [ "$UNITS" = "0" ]; then
    log "按参数要求跳过"
elif [ "$DRY" = "1" ]; then
    log "[dry-run] cp wsl/qq-bot.service wsl/qq-napcat.service $UNIT_DEST/"
    log "[dry-run] systemctl --user daemon-reload（只重读单元文件，不影响运行中的微信服务）"
else
    for unit in qq-bot qq-napcat; do
        src="$HERE/$unit.service"
        [ -f "$src" ] || die "缺少单元文件 $src"
        cp "$src" "$UNIT_DEST/$unit.service"
        # 仓库在 /mnt/d（drvfs 权限是 777），加上 umask 077 复制过来会变成 700，
        # systemd 会告警 "marked executable"。显式 644：单元文件是配置，不是可执行程序。
        chmod 644 "$UNIT_DEST/$unit.service"
        log "已安装 $UNIT_DEST/$unit.service"
    done
    systemctl --user daemon-reload
    log "daemon-reload 完成（不会重启/停止任何正在运行的服务，微信服务不受影响）"
fi

step "端口占用速查（只读，不改任何东西）"
if command -v ss >/dev/null 2>&1; then
    for p in "$PORT" 6099; do
        if [ -n "$(ss -ltnH "sport = :$p" 2>/dev/null || true)" ]; then
            warn "端口 $p 已被占用（18080=反向 WS / 6099=NapCat WebUI）；占用的不是 QQ 侧进程就要先查清楚"
        else
            log "端口 $p 空闲"
        fi
    done
else
    warn "系统里没有 ss（iproute2），跳过端口检查"
fi

step "剩下的必须由人来做（本脚本刻意不碰）"
cat <<'NEXTEOF'
  1) 确认 NapCat 装好了（第三方组件，本机按 rootless 方式装在 ~/Napcat，不需要 sudo）：
       $ ls ~/Napcat/opt/QQ/qq        # 有输出就是装好了；没有则照 docs/QQ.md 的安装一节走
  2) 启动 + 扫码登录（NapCat 是 QQ 客户端，必须人工扫一次）：
       $ screen -dmS napcat xvfb-run -a ~/Napcat/opt/QQ/qq --no-sandbox
       $ screen -r napcat             # 看启动日志里的 WebUI 地址与 token（Ctrl-A D 退回）
  3) WebUI 改密 + 把 host 改成 127.0.0.1（默认 0.0.0.0 会暴露到局域网）：
       $ cat ~/Napcat/opt/QQ/resources/app/app_launcher/napcat/config/webui.json
  4) 在 WebUI 里新建"WebSocket 客户端"（反向 WS），指向 NoneBot：
       url = ws://127.0.0.1:18080/onebot/v11/ws   token = qq.env 里的 QQ_BOT_ONEBOT_TOKEN
       messagePostFormat = array      reportSelfMessage = false      "保存时启用"要勾上
  5) 起服务前先做一次启动自检（0=可启动 / 2=token 或端口 / 3=依赖或核心模块）：
       $ cd /mnt/d/AgentPrograms/wechat-bot && QQ_BOT_CONFIG=$HOME/.config/qq-bot/qq.json \
           QQ_BOT_ONEBOT_TOKEN=$(grep ^QQ_BOT_ONEBOT_TOKEN= $HOME/.config/qq-bot/qq.env | cut -d= -f2-) \
           $HOME/.local/share/qq-bot/venv/bin/python -m qq.bot --check
  6) 起 QQ 服务（只动 QQ 的单元，微信一行不碰）：
       $ systemctl --user enable --now qq-bot
       $ systemctl --user status qq-bot --no-pager
       # 想让 NapCat 也交给 systemd 管（替代 screen）：systemctl --user enable --now qq-napcat
  7) 先急停、再验收（分阶段闸门见 docs/QQ.md，别一上来就放开群回复）：
       $ touch ~/.local/state/qq-bot/STOP
       $ python3 /mnt/d/AgentPrograms/wechat-bot/wsl/qq-acceptance.py
       $ python3 /mnt/d/AgentPrograms/wechat-bot/wsl/qq-health.py
NEXTEOF

if [ "$DRY" = "1" ]; then
    log "dry-run 结束：上面列出的是真跑时会做的事，本次没有落盘任何文件"
else
    log "安装完成：环境已就绪，但【没有启动任何服务】（这是故意的）"
    log "下一步：按上面 6 步走，或直接看 docs/QQ.md"
fi
