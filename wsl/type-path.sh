#!/bin/bash
export DISPLAY=:99
W=14680155
IMG=/home/niangao/.local/state/wechat-bot/media/gen-1792077117.png
ls -la $IMG
xdotool windowactivate $W
sleep 0.6
echo "--- 点击 File name 输入框 ---"
xdotool mousemove 639 586 click 1
sleep 0.4
xdotool key ctrl+a
sleep 0.2
echo "--- 输入图片路径 ---"
xdotool type "$IMG"
sleep 0.8
import -window $W /tmp/dlg-typed.png
cp /tmp/dlg-typed.png /mnt/d/AgentPrograms/wechat-bot/wsl/dialog-typed.png
python3 - <<'PY'
import json, subprocess
from PIL import Image
im = Image.open('/tmp/dlg-typed.png').convert('RGB')
# 只 OCR 底部两行（File name 行 + 按钮行）
crop = im.crop((0, 350, 650, 400))
crop = crop.resize((crop.width*2, crop.height*2))
crop.save('/tmp/dlg-bottom.png')
out = subprocess.run(['tesseract','/tmp/dlg-bottom.png','stdout','-l','eng','--psm','6'],
                     capture_output=True, text=True, timeout=60).stdout
print(json.dumps({'bottom_ocr': out.strip()[:300]}, ensure_ascii=False))
PY
