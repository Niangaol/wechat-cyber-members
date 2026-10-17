#!/bin/bash
export DISPLAY=:99
echo "=== 窗口 ==="
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  g=$(xdotool getwindowgeometry $w 2>/dev/null | grep Geometry | tr -d ' ')
  case "$n" in Weixin|Moments|Open) echo "$w | $n | $g";; esac
done
echo "=== llama-server 还活着? ==="
pgrep -f "llama-server" >/dev/null && echo "RUNNING pid=$(pgrep -f llama-server | head -1)" || echo "DEAD"
curl -s -o /dev/null -w "http=%{http_code}
" --max-time 5 http://127.0.0.1:8088/v1/models
echo "=== 显存 ==="
nvidia-smi --query-gpu=memory.used --format=csv,noheader
echo "=== 账本 ==="
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/ledger-report.py 2>&1 | head -8
