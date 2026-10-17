#!/bin/bash
export DISPLAY=:99
W=$(xdotool search --name "^Open$" | head -1)
# 先点字段，再键入可见字符
xdotool windowactivate $W; sleep 0.4
xdotool mousemove 639 586 click 1; sleep 0.4
xdotool type "QQQ"; sleep 0.6
import -window $W /tmp/dlg-q.png
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/tmp/dlg-q.png').convert('RGB')
# 放大 File name 行整行（含标签和按钮）
crop = im.crop((0, 350, 650, 395))
crop = crop.resize((crop.width*3, crop.height*3), Image.LANCZOS)
crop.save('/mnt/d/AgentPrograms/wechat-bot/wsl/field-zoom.png')
print(json.dumps({'saved': 'field-zoom.png', 'size': list(crop.size)}))
PY
