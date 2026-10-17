#!/bin/bash
export DISPLAY=:99
W=14680155
IMG=/home/niangao/.local/state/wechat-bot/media/gen-1792077117.png
# 先把路径写进剪贴板（和 wechat_ui.clipboard_write 同一机制）
printf '%s' "$IMG" | xsel --clipboard --input
echo "clipboard: [$(xsel --clipboard --output)]"
xdotool windowactivate $W
sleep 0.6
echo "--- 点击 File name 输入框 (639,586) ---"
xdotool mousemove 639 586 click 1
sleep 0.5
echo "--- ctrl+a 全选 ---"
xdotool key ctrl+a
sleep 0.3
echo "--- ctrl+v 粘贴 ---"
xdotool key ctrl+v
sleep 1.0
import -window $W /tmp/dlg-pasted.png
cp /tmp/dlg-pasted.png /mnt/d/AgentPrograms/wechat-bot/wsl/dialog-pasted.png
python3 - <<'PY'
import json, subprocess
from PIL import Image
im = Image.open('/tmp/dlg-pasted.png').convert('RGB')
crop = im.crop((0, 350, 650, 400))
crop = crop.resize((crop.width*2, crop.height*2))
crop.save('/tmp/dlg-bottom.png')
out = subprocess.run(['tesseract','/tmp/dlg-bottom.png','stdout','-l','eng','--psm','6'],
                     capture_output=True, text=True, timeout=60).stdout
print(json.dumps({'bottom_ocr': out.strip()[:300]}, ensure_ascii=False))
PY
