#!/usr/bin/env bash
# QQ 链路真机自检驱动（lead 编写）：跑三种场景，全部用"假 NapCat"，不需要真实 QQ 登录。
#
#   1) 私聊（白名单内）        → 期望：收到 send_msg（走通 生成→发送→台账）
#   2) 群里不 @                → 期望：不发送（只进上下文）
#   3) 群里的真 @（at 段）     → 期望：收到 send_msg（发给 group_id）
#   4) 同 message_id 重投      → 期望：不重复回复（持久去重）
#
# 用法：wsl -d Ubuntu-24.04 -- bash /mnt/d/AgentPrograms/wechat-bot/wsl/qq-e2e-live-check.sh
# 前置：qq-bot 已启动；~/.config/qq-bot/qq.json 里 auto_send=true、目标号/群号已登记、测试号在白名单里。
set -u
ROOT=/mnt/d/AgentPrograms/wechat-bot
VENV=$HOME/.local/share/qq-bot/venv/bin/python
cd "$ROOT" || exit 3

echo "=== 0) 服务状态 ==="
systemctl --user is-active qq-bot || true

echo "=== 1) 私聊（白名单内）==="
"$VENV" wsl/qq-e2e-fake-napcat.py --user 20002 --message-id 930001 --text "自检一句" --timeout 100 2>&1 | tail -4

echo "=== 2) 群里不 @（应超时=不发送）==="
"$VENV" wsl/qq-e2e-fake-napcat.py --chat-type group --group 888777 --user 20003 --message-id 930002 --text "群里闲聊一句" --timeout 20 2>&1 | tail -3

echo "=== 3) 群里真 @（应发送）==="
"$VENV" wsl/qq-e2e-fake-napcat.py --chat-type group --group 888777 --user 20003 --at --message-id 930003 --text "在吗" --timeout 100 2>&1 | tail -4

echo "=== 4) 同 message_id 重投（不应重复回复）==="
"$VENV" wsl/qq-e2e-fake-napcat.py --user 20002 --message-id 930001 --text "自检一句" --timeout 20 2>&1 | tail -3

echo "=== 5) 最近日志 ==="
journalctl --user -u qq-bot --since -6min --no-pager | grep -E "qq_event|qq_reply_sent|qq_send|qq_auto" | tail -12

echo "=== 6) 台账 ==="
"$VENV" - <<"PY"
import sqlite3
from pathlib import Path
db = sqlite3.connect(str(Path.home()/".local/state/qq-bot/qq.db"))
print("usage(模型调用次数):", db.execute("select count(*) from usage").fetchone()[0])
print("inbound(去重行数):", db.execute("select count(*) from inbound").fetchone()[0])
for row in db.execute("select chat_key,kind,state,detail from send_log order by id desc limit 5"):
    print("send_log:", row)
PY
