#!/bin/bash
export DISPLAY=:99
MW=14680150   # Moments 窗口
run() { timeout 10 "$@" || echo "CMD_TIMEOUT: $*"; }
echo "=== 1. 用 --window 点相机图标（Moments 窗口内 77,22）==="
run xdotool mousemove --window $MW 77 22
run xdotool click --window $MW 1
sleep 3
DW=$(timeout 10 xdotool search --name "^Open$" 2>/dev/null | head -1)
echo "file dialog wid=$DW"
if [ -z "$DW" ]; then echo "NO_DIALOG"; exit 1; fi
echo "=== 2. --window 点 File name 字段（对话框内 323,373）==="
run xdotool mousemove --window $DW 323 373
run xdotool click --window $DW 1
sleep 0.6
echo "=== 3. --window 键入路径 ==="
run xdotool type --window $DW "/home/niangao/xwechat_files/moment-test.png"
sleep 0.8
run import -window $DW /tmp/dlg-final.png
cp /tmp/dlg-final.png /mnt/d/AgentPrograms/wechat-bot/wsl/dialog-window-click.png
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/tmp/dlg-final.png').convert('RGB')
crop = im.crop((90, 355, 650, 395))
crop = crop.resize((crop.width*2, crop.height*2), Image.LANCZOS)
crop.save('/mnt/d/AgentPrograms/wechat-bot/wsl/field-final.png')
print(json.dumps({'saved': True}))
PY
