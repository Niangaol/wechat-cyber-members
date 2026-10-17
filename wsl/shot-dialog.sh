#!/bin/bash
export DISPLAY=:99
for W in 14680155 14680150; do
  import -window $W /tmp/win-$W.png 2>&1 && echo "$W ok $(stat -c%s /tmp/win-$W.png)" || echo "$W FAIL"
done
cp /tmp/win-14680155.png /mnt/d/AgentPrograms/wechat-bot/wsl/file-dialog.png
cp /tmp/win-14680150.png /mnt/d/AgentPrograms/wechat-bot/wsl/moments-after-camera.png
echo "--- Open 窗口几何 ---"
xdotool getwindowgeometry 14680155 2>&1 | tr '\n' ' '; echo
echo "--- Open 窗口内容 OCR ---"
python3 - <<'PY'
import subprocess, json
from PIL import Image
im = Image.open('/tmp/win-14680155.png').convert('RGB')
im2 = im.resize((im.width*2, im.height*2))
im2.save('/tmp/dlg-2x.png')
out = subprocess.run(['tesseract','/tmp/dlg-2x.png','stdout','-l','eng','--psm','6'],
                     capture_output=True, text=True, timeout=60).stdout
print(json.dumps({'ocr': out.strip()[:500]}, ensure_ascii=False))
PY
