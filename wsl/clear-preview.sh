#!/bin/bash
export DISPLAY=:99
W=14680080
run() { timeout 12 "$@" || echo "TIMEOUT: $*"; }
echo "=== 先点一下输入框确保焦点 ==="
run xdotool mousemove 600 630
run xdotool click 1
sleep 0.5
echo "=== 试 Backspace ==="
run xdotool key --window $W --clearmodifiers BackSpace
sleep 1
import -window $W /tmp/b1.png
echo "=== 试 Delete ==="
run xdotool key --window $W --clearmodifiers Delete
sleep 1
import -window $W /tmp/b2.png
python3 - <<'PY'
import json
from PIL import Image
for tag, p in (('after_backspace','/tmp/b1.png'), ('after_delete','/tmp/b2.png')):
    im = Image.open(p).convert('RGB')
    zone = im.crop((283, 540, 945, 605)).convert('L')
    n = sum(1 for v in zone.getdata() if v < 235)
    print(json.dumps({tag: n, 'cleared': n < 500}, ensure_ascii=False))
PY
cp /tmp/b2.png /mnt/d/AgentPrograms/wechat-bot/wsl/after-keydel.png
