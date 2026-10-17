#!/bin/bash
export DISPLAY=:99
echo "=== 窗口与消息状态 ==="
import -window 14680080 /tmp/r35.png
python3 - <<'PY'
import subprocess, json
from PIL import Image
im = Image.open('/tmp/r35.png').convert('RGB')
# 健康度
content = im.crop((396, 120, 1058, 620))
px = list(content.getdata())
dark = sum(1 for p in px if sum(p) < 60)
# 最后一条消息的时间（内容区右下角附近）
im.crop((950, 560, 1055, 620)).resize((315, 180), Image.LANCZOS).save('/tmp/lastmsg.png')
out = subprocess.run(['tesseract','/tmp/lastmsg.png','stdout','-l','eng','--psm','6'],
                     capture_output=True, text=True, timeout=60).stdout
print(json.dumps({'healthy': dark/len(px) < 0.3,
                  'last_time_area': out.strip()[:40]}, ensure_ascii=False))
PY
echo "=== 工具栏全宽放大 ==="
python3 - <<'PY'
from PIL import Image
im = Image.open('/tmp/r35.png').convert('RGB')
crop = im.crop((290, 585, 500, 620))
crop = crop.resize((crop.width*3, crop.height*3), Image.LANCZOS)
crop.save('/mnt/d/AgentPrograms/wechat-bot/wsl/toolbar-full.png')
print('saved')
PY
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments|Chat*) echo "$w | $n";; esac
done
