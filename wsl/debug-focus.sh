#!/bin/bash
export DISPLAY=:99
echo "--- Open 窗口几何（可能变过） ---"
for W in $(xdotool search --name "^Open$" 2>/dev/null); do
  xdotool getwindowgeometry $W 2>&1 | tr '\n' ' '; echo " (wid=$W)"
done
echo "--- 当前输入焦点窗口 ---"
FW=$(xdotool getwindowfocus 2>/dev/null)
echo "focus wid=$FW name=[$(xdotool getwindowname $FW 2>/dev/null)]"
echo "--- 活动窗口 ---"
AW=$(xdotool getactivewindow 2>/dev/null)
echo "active wid=$AW name=[$(xdotool getwindowname $AW 2>/dev/null)]"
echo "--- 点击输入框后焦点去哪 ---"
xdotool windowactivate $(xdotool search --name "^Open$" | head -1)
sleep 0.5
xdotool mousemove 639 586 click 1
sleep 0.5
FW2=$(xdotool getwindowfocus 2>/dev/null)
echo "after click: focus wid=$FW2 name=[$(xdotool getwindowname $FW2 2>/dev/null)]"
echo "--- 试直接键入 abc 看是否出现 ---"
xdotool type "ZZZTEST"
sleep 0.6
import -window $(xdotool search --name "^Open$" | head -1) /tmp/dlg-type-test.png
python3 - <<'PY'
import json, subprocess
from PIL import Image
im = Image.open('/tmp/dlg-type-test.png').convert('RGB')
crop = im.crop((90, 355, 560, 390)).resize((940, 70))
crop.save('/tmp/field.png')
out = subprocess.run(['tesseract','/tmp/field.png','stdout','-l','eng','--psm','7'],
                     capture_output=True, text=True, timeout=60).stdout
print(json.dumps({'field_ocr': out.strip()[:200]}, ensure_ascii=False))
PY
