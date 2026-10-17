#!/bin/bash
export DISPLAY=:99
cd /mnt/d/AgentPrograms/wechat-bot
W=14680080
# 记录点击前的内容区指纹（用于证明面板真的切换了）
import -window $W /tmp/before-moments.png
python3 - <<'PY'
import json, hashlib
from PIL import Image
im = Image.open('/tmp/before-moments.png').convert('RGB')
# 内容区：侧边栏右侧、顶部标题栏下方、底部工具栏上方
crop = im.crop((283, 90, 1021, 590))
print(json.dumps({'before_fingerprint': hashlib.sha256(crop.tobytes()).hexdigest()[:16]}))
PY
echo "--- 点击朋友圈图标 (145,282) ---"
xdotool mousemove 145 282 click 1
sleep 3
import -window $W /tmp/after-moments.png
python3 - <<'PY'
import json, hashlib
from PIL import Image
im = Image.open('/tmp/after-moments.png').convert('RGB')
crop = im.crop((283, 90, 1021, 590))
print(json.dumps({'after_fingerprint': hashlib.sha256(crop.tobytes()).hexdigest()[:16],
                  'size': list(im.size)}))
PY
cp /tmp/after-moments.png /mnt/d/AgentPrograms/wechat-bot/wsl/moments-panel.png
echo "saved"
