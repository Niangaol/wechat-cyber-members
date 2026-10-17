#!/bin/bash
export DISPLAY=:99
echo "=== 窗口 ==="
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  g=$(xdotool getwindowgeometry $w 2>/dev/null | grep Geometry | tr -d ' ')
  case "$n" in Weixin|Moments|Open) echo "$w | $n | $g";; esac
done
echo "=== 主窗口内容是否正常（非黑屏）==="
import -window 14680080 /tmp/chk.png 2>/dev/null
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/tmp/chk.png').convert('RGB')
crop = im.crop((283, 90, 1021, 590))
px = list(crop.getdata())
dark = sum(1 for p in px if sum(p) < 60)
print(json.dumps({'size': list(im.size),
                  'dark_pct': round(100*dark/len(px),1),
                  'healthy': dark/len(px) < 0.3}))
PY
echo "=== 账本 ==="
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/ledger-report.py 2>&1 | head -5
