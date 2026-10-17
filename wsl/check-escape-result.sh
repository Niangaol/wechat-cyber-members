#!/bin/bash
export DISPLAY=:99
import -window 14680080 /tmp/after-esc.png
cp /tmp/after-esc.png /mnt/d/AgentPrograms/wechat-bot/wsl/after-escape-check.png
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/tmp/after-esc.png').convert('RGB')
# 预览区 (283,540,945,605) 和输入框 (283,605,945,654)
prev = im.crop((283, 540, 945, 605)).convert('L')
inp = im.crop((283, 605, 945, 654)).convert('L')
pn = sum(1 for v in prev.getdata() if v < 235)
print(json.dumps({'preview_nonwhite_px': pn,
                  'preview_cleared': pn < 500,
                  'threshold': 500}, ensure_ascii=False))
PY
