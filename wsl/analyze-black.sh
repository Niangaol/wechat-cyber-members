#!/bin/bash
export DISPLAY=:99
python3 - <<'PY'
import json
from PIL import Image
from collections import Counter
im = Image.open('/tmp/moments3.png').convert('RGB')
crop = im.crop((283, 90, 1021, 590))
px = list(crop.getdata())
n = len(px)
pure_black = sum(1 for p in px if p == (0, 0, 0))
near_black = sum(1 for p in px if sum(p) < 30)
dark = sum(1 for p in px if sum(p) < 120)
light = sum(1 for p in px if sum(p) > 600)
top = Counter(px).most_common(6)
print(json.dumps({
    'total_px': n,
    'pure_black_pct': round(100*pure_black/n, 1),
    'near_black_pct': round(100*near_black/n, 1),
    'dark_pct': round(100*dark/n, 1),
    'light_pct': round(100*light/n, 1),
    'top_colors': [(list(c), round(100*k/n, 1)) for c, k in top],
}, ensure_ascii=False))
# 也看一眼聊天页做对照
im2 = Image.open('/tmp/back-to-chat.png').convert('RGB')
c2 = im2.crop((283, 90, 1021, 590))
px2 = list(c2.getdata())
print(json.dumps({'chat_light_pct': round(100*sum(1 for p in px2 if sum(p) > 600)/len(px2), 1),
                  'chat_pure_black_pct': round(100*sum(1 for p in px2 if p == (0,0,0))/len(px2), 1)}))
PY
