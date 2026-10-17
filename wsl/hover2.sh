#!/bin/bash
export DISPLAY=:99
W=14680080
import -window $W /tmp/full.png
cp /tmp/full.png /mnt/d/AgentPrograms/wechat-bot/wsl/current-full.png
python3 - <<'PY'
from PIL import Image
im = Image.open('/tmp/full.png').convert('RGB')
# 输入框区域全高裁剪放大
im.crop((283, 585, 960, 680)).resize((1353, 190), Image.LANCZOS).save('/mnt/d/AgentPrograms/wechat-bot/wsl/input-zoom.png')
print('saved')
PY
echo "=== hover 预览本体 (600,625) ==="
timeout 10 xdotool mousemove 600 625
sleep 1
import -window $W /tmp/hov.png
cp /tmp/hov.png /mnt/d/AgentPrograms/wechat-bot/wsl/hover-preview.png
python3 - <<'PY'
from PIL import Image
im = Image.open('/tmp/hov.png').convert('RGB')
im.crop((283, 585, 960, 680)).resize((1353, 190), Image.LANCZOS).save('/mnt/d/AgentPrograms/wechat-bot/wsl/hover-zoom.png')
print('hover zoom saved')
PY
