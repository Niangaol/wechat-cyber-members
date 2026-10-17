#!/bin/bash
export DISPLAY=:99
import -window 14680080 /tmp/state.png
cp /tmp/state.png /mnt/d/AgentPrograms/wechat-bot/wsl/r34-state.png
python3 - <<'PY'
import subprocess, json
from PIL import Image
im = Image.open('/tmp/state.png').convert('RGB')
# 主窗口内容区健康度
content = im.crop((396, 120, 1058, 620))
px = list(content.getdata())
dark = sum(1 for p in px if sum(p) < 60)
# 标题区 OCR
title = im.crop((396, 30, 1058, 75))
title.save('/tmp/title34.png')
out = subprocess.run(['tesseract','/tmp/title34.png','stdout','-l','chi_sim+eng','--psm','7'],
                     capture_output=True, text=True, timeout=60).stdout
print(json.dumps({'healthy': dark/len(px) < 0.3,
                  'title': out.strip()[:60]}, ensure_ascii=False))
PY
echo "=== 窗口 ==="
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments|Open) echo "$w | $n";; esac
done
