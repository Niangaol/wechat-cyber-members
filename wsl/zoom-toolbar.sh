#!/bin/bash
export DISPLAY=:99
python3 - <<'PY'
from PIL import Image
im = Image.open('/tmp/state.png').convert('RGB')
# 工具栏区域放大（原图 396..620, 585..620）
crop = im.crop((396, 585, 620, 620))
crop = crop.resize((crop.width*4, crop.height*4), Image.LANCZOS)
crop.save('/mnt/d/AgentPrograms/wechat-bot/wsl/toolbar-zoom.png')
print('saved', crop.size)
PY
