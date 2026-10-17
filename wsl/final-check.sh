#!/bin/bash
export DISPLAY=:99
echo "=== 编辑页还在吗 ==="
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments|Open) echo "$w | $n";; esac
done
import -window root /tmp/final-check.png
cp /tmp/final-check.png /mnt/d/AgentPrograms/wechat-bot/wsl/screen-final-check.png
echo "=== llama-server ==="
pgrep -f llama-server >/dev/null && echo RUNNING || echo DEAD
echo "=== 账本 ==="
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/ledger-report.py 2>&1 | head -6
