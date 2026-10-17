#!/bin/bash
export DISPLAY=:99
which xclip xsel 2>&1
echo "=== 选一张测试图（OC参考图 667KB < 20MB）==="
ls -la /mnt/d/AgentPrograms/wechat-bot/config/assets/oc-reference.png
python3 - <<'PY'
from PIL import Image
im = Image.open('/mnt/d/AgentPrograms/wechat-bot/config/assets/oc-reference.png')
print('size', im.size, 'mode', im.mode)
# 生成一张缩略版加快粘贴（512px）
im2 = im.convert('RGB')
im2.thumbnail((512, 512))
im2.save('/tmp/oc-thumb.png')
print('thumb saved')
PY
ls -la /tmp/oc-thumb.png
