#!/bin/bash
export DISPLAY=:99
W=$(xdotool search --name "^Open$" | head -1)
xdotool windowactivate $W; sleep 0.4
echo "--- 双击 xwechat_files 文件夹（窗口内约 350,118 → 绝对 666,331）---"
xdotool mousemove 666 331 click 1 click 1
sleep 2
import -window $W /tmp/dlg-nav.png
cp /tmp/dlg-nav.png /mnt/d/AgentPrograms/wechat-bot/wsl/dialog-navigated.png
python3 - <<'PY'
import json, subprocess
from PIL import Image
im = Image.open('/tmp/dlg-nav.png').convert('RGB')
crop = im.crop((150, 55, 650, 200))
crop = crop.resize((crop.width*2, crop.height*2))
crop.save('/tmp/list.png')
out = subprocess.run(['tesseract','/tmp/list.png','stdout','-l','eng','--psm','6'],
                     capture_output=True, text=True, timeout=60).stdout
print(json.dumps({'list_ocr': out.strip()[:300]}, ensure_ascii=False))
PY
