#!/bin/bash
export DISPLAY=:99
W=14680080
sleep 6
import -window $W /tmp/moments2.png
cp /tmp/moments2.png /mnt/d/AgentPrograms/wechat-bot/wsl/moments-panel2.png
python3 - <<'PY'
import json, hashlib
from PIL import Image
im = Image.open('/tmp/moments2.png').convert('RGB')
crop = im.crop((283, 90, 1021, 590))
h = hashlib.sha256(crop.tobytes()).hexdigest()[:16]
# 统计内容区平均亮度：全黑=还在加载；有内容=已渲染
px = list(crop.getdata())
avg = sum(sum(p) for p in px[::97]) / (3*len(px[::97]))
print(json.dumps({'fingerprint': h, 'avg_brightness': round(avg,1)}))
PY
echo "--- 窗口标题 ---"
xdotool getwindowname $W
