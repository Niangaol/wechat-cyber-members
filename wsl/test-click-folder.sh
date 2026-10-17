#!/bin/bash
export DISPLAY=:99
W=$(xdotool search --name "^Open$" | head -1)
echo "geometry: $(xdotool getwindowgeometry $W | tr '\n' ' ')"
import -window $W /tmp/dlg-before.png
echo "--- 点击 wechat-install 文件夹行（窗口内约 350,95）---"
xdotool mousemove 666 308 click 1
sleep 1.5
import -window $W /tmp/dlg-after.png
python3 - <<'PY'
import json, hashlib
from PIL import Image
a = Image.open('/tmp/dlg-before.png').convert('RGB')
b = Image.open('/tmp/dlg-after.png').convert('RGB')
fa = hashlib.sha256(a.tobytes()).hexdigest()[:12]
fb = hashlib.sha256(b.tobytes()).hexdigest()[:12]
print(json.dumps({'before': fa, 'after': fb, 'changed': fa != fb}))
b.save('/mnt/d/AgentPrograms/wechat-bot/wsl/dialog-after-folder-click.png')
PY
