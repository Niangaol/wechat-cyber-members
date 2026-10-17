#!/bin/bash
export DISPLAY=:99
W=$(xdotool search --name "^Open$" | head -1)
echo "--- 双击 File name 字段 (639,586) ---"
xdotool mousemove 639 586 click 1 click 1
sleep 0.8
import -window $W /tmp/dlg-dbl.png
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/tmp/dlg-dbl.png').convert('RGB')
crop = im.crop((95, 358, 555, 388))
crop = crop.resize((crop.width*3, crop.height*3), Image.LANCZOS)
crop.save('/mnt/d/AgentPrograms/wechat-bot/wsl/field-zoom2.png')
# 检测字段内是否有选中高亮（蓝色背景）
px = crop.load()
blue = sum(1 for y in range(0, crop.height, 2) for x in range(0, crop.width, 2)
           if px[x, y][2] > 120 and px[x, y][2] - px[x, y][0] > 40)
print(json.dumps({'blue_highlight_px': blue, 'looks_selected': blue > 50}))
PY
