#!/bin/bash
# 登录成功后一键验收：等主窗口 -> 截图 -> 批量 OCR A/B 3 轮 -> 账本状态
set -u
export DISPLAY=:99
cd /mnt/d/AgentPrograms/wechat-bot

echo "=== 1. 等待微信主窗口（最多 180 秒）==="
ok=""
for i in $(seq 1 90); do
  W=$(xdotool search --name "^Weixin$" 2>/dev/null | head -1)
  G=$(xdotool getwindowgeometry "$W" 2>/dev/null | tr '\n' ' ')
  if [ -n "$W" ] && echo "$G" | grep -q "1021x740"; then
    ok="$W"; echo "主窗口就绪: $W $G"; break
  fi
  sleep 2
done
[ -z "$ok" ] && { echo "FAIL: 180 秒内未见 1021x740 主窗口（可能还在扫码页或掉线）"; exit 1; }

xdotool windowactivate "$ok" 2>/dev/null
sleep 1
echo "=== 2. 截图 ==="
import -window "$ok" /tmp/main.png && echo "shot $(stat -c%s /tmp/main.png) bytes"

echo "=== 3. 批量 OCR A/B（本地 vs step-3.7-flash，3 轮）==="
python3 wsl/verify-batch-ocr.py --count 3 --wait 3

echo "=== 4. 账本与队列状态 ==="
python3 wsl/ledger-report.py 2>&1 | tail -12
