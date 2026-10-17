#!/bin/bash
export DISPLAY=:99
W=14680080
run() { timeout 12 "$@" || echo "TIMEOUT: $*"; }
echo "=== 方法1: ctrl+a 全选 + Delete ==="
run xdotool mousemove 700 625
run xdotool click 1
sleep 0.4
run xdotool key --window $W --clearmodifiers ctrl+a
sleep 0.6
import -window $W /tmp/ca.png
run xdotool key --window $W --clearmodifiers Delete
sleep 1
import -window $W /tmp/cad.png
python3 - <<'PY'
import json
from PIL import Image
for tag, p in (('after_ctrl_a','/tmp/ca.png'), ('after_ctrl_a_del','/tmp/cad.png')):
    im = Image.open(p).convert('RGB')
    zone = im.crop((283, 600, 945, 660)).convert('L')
    n = sum(1 for v in zone.getdata() if v < 235)
    print(json.dumps({tag: n, 'cleared': n < 500}, ensure_ascii=False))
PY
cp /tmp/cad.png /mnt/d/AgentPrograms/wechat-bot/wsl/after-ctrla-del.png
