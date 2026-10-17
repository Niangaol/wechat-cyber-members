#!/bin/bash
# 启动烤机体检（幂等：先停旧的再起新的）
set -u
cd /mnt/d/AgentPrograms/wechat-bot || exit 1
STATE="$HOME/.local/state/wechat-bot"
pkill -f '[s]oak.py' 2>/dev/null
sleep 1
export SOAK_INTERVAL="${SOAK_INTERVAL:-30}"
export SOAK_DURATION="${SOAK_DURATION:-5400}"
export SOAK_TAG="${SOAK_TAG:-r58}"
nohup python3 wsl/soak.py > "$STATE/soak-$SOAK_TAG.log" 2>&1 &
sleep 45
echo "=== PROC ==="
pgrep -af '[s]oak'
echo "=== LOG ==="
cat "$STATE/soak-$SOAK_TAG.log"
echo "=== SAMPLES ==="
wc -l "$STATE/soak-$SOAK_TAG.jsonl" 2>/dev/null || echo "no samples yet"
tail -1 "$STATE/soak-$SOAK_TAG.jsonl" 2>/dev/null
