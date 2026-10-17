#!/bin/bash
export DISPLAY=:99
echo "=== 点侧边栏测试群名恢复渲染 ==="
timeout 10 xdotool mousemove 273 161
timeout 10 xdotool click 1
sleep 3
import -window 14680080 /tmp/rec.png
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/tmp/rec.png').convert('RGB')
crop = im.crop((283, 90, 1021, 590))
px = list(crop.getdata())
dark = sum(1 for p in px if sum(p) < 60)
zone = im.crop((283, 540, 945, 605)).convert('L')
n = sum(1 for v in zone.getdata() if v < 235)
print(json.dumps({'dark_pct': round(100*dark/len(px),1),
                  'healthy': dark/len(px) < 0.3,
                  'preview_nonwhite_px': n,
                  'preview_still_there': n >= 500}, ensure_ascii=False))
PY
cp /tmp/rec.png /mnt/d/AgentPrograms/wechat-bot/wsl/recovered-input.png
