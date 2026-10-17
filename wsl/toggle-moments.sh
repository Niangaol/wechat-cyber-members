#!/bin/bash
export DISPLAY=:99
W=14680080
echo "--- 点回聊天图标 (147,127) ---"
xdotool mousemove 147 127 click 1
sleep 3
import -window $W /tmp/back-to-chat.png
python3 - <<'PY'
import json, hashlib
from PIL import Image
im = Image.open('/tmp/back-to-chat.png').convert('RGB')
crop = im.crop((283, 90, 1021, 590))
px = list(crop.getdata())
avg = sum(sum(p) for p in px[::97]) / (3*len(px[::97]))
print(json.dumps({'fingerprint': hashlib.sha256(crop.tobytes()).hexdigest()[:16],
                  'avg_brightness': round(avg,1),
                  'before_moments_was': '8144a56bbe23e4ef'}))
PY
cp /tmp/back-to-chat.png /mnt/d/AgentPrograms/wechat-bot/wsl/back-to-chat.png
echo "--- 再点一次朋友圈，等10秒看是否偶发 ---"
xdotool mousemove 145 282 click 1
sleep 10
import -window $W /tmp/moments3.png
python3 - <<'PY'
import json, hashlib
from PIL import Image
im = Image.open('/tmp/moments3.png').convert('RGB')
crop = im.crop((283, 90, 1021, 590))
px = list(crop.getdata())
avg = sum(sum(p) for p in px[::97]) / (3*len(px[::97]))
print(json.dumps({'fingerprint': hashlib.sha256(crop.tobytes()).hexdigest()[:16],
                  'avg_brightness': round(avg,1)}))
PY
