#!/bin/bash
export DISPLAY=:99
echo "=== 激活主窗口再点笑脸 ==="
timeout 10 xdotool windowactivate 14680080
sleep 0.8
timeout 10 xdotool mousemove 312 605
sleep 0.5
timeout 10 xdotool click 1
sleep 2.5
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/tmp/smile4.png').convert('RGB')  # 旧图占位
PY
import -window root /tmp/smile5.png
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/tmp/smile5.png').convert('RGB')
main = im.crop((396, 585, 1058, 740))
px = list(main.getdata())
dark = sum(1 for p in px if sum(p) < 200)
print(json.dumps({'below_toolbar_nonbg_px': dark, 'panel_open': dark > 2000}, ensure_ascii=False))
PY
cp /tmp/smile5.png /mnt/d/AgentPrograms/wechat-bot/wsl/smile-activated.png
