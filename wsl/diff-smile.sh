#!/bin/bash
python3 - <<'PY'
import json
from PIL import Image, ImageChops
a = Image.open('/tmp/r35.png').convert('RGB')       # 点击前
b = Image.open('/tmp/burst-1.png').convert('RGB')   # 点击后
diff = ImageChops.difference(a, b)
bbox = diff.getbbox()
print(json.dumps({'diff_bbox': list(bbox) if bbox else None}, ensure_ascii=False))
if bbox:
    # 把变化区域裁剪放大
    pad = 20
    x1, y1, x2, y2 = bbox
    crop = b.crop((max(0,x1-pad), max(0,y1-pad), min(1021,x2+pad), min(740,y2+pad)))
    crop.save('/mnt/d/AgentPrograms/wechat-bot/wsl/smile-diff-zone.png')
    print('diff zone saved', crop.size)
# 同时存整图
b.save('/mnt/d/AgentPrograms/wechat-bot/wsl/after-smile-burst.png')
PY
