#!/bin/bash
export DISPLAY=:99
echo "=== 最终状态确认 ==="
import -window root /tmp/final-r33.png
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/tmp/final-r33.png').convert('RGB')
# 主窗口输入框区
main = im.crop((396, 620, 1058, 680)).convert('L')
n = sum(1 for v in main.getdata() if v < 235)
# 主窗口内容区健康度
content = im.crop((396, 120, 1058, 620))
px = list(content.getdata())
dark = sum(1 for p in px if sum(p) < 60)
print(json.dumps({'main_content_dark_pct': round(100*dark/len(px),1),
                  'healthy': dark/len(px) < 0.3}, ensure_ascii=False))
PY
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments) echo "$w | $n";; esac
done
echo "=== 账本 ==="
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/ledger-report.py 2>&1 | head -4
