#!/bin/bash
export DISPLAY=:99
run() { timeout 10 "$@" || echo "CMD_TIMEOUT: $*"; }
DW=$(timeout 10 xdotool search --name "^Open$" 2>/dev/null | head -1)
echo "dialog wid=$DW"
[ -z "$DW" ] && { echo NO_DIALOG; exit 1; }
echo "=== 点字段 → ctrl+a 全选 → 键入路径 ==="
run xdotool mousemove --window $DW 323 373
run xdotool click --window $DW 1
sleep 0.4
run xdotool key --window $DW ctrl+a
sleep 0.3
run xdotool type --window $DW "/home/niangao/xwechat_files/moment-test.png"
sleep 0.8
run import -window $DW /tmp/dlg-final2.png
cp /tmp/dlg-final2.png /mnt/d/AgentPrograms/wechat-bot/wsl/dialog-path-ready.png
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/tmp/dlg-final2.png').convert('RGB')
crop = im.crop((90, 355, 650, 395))
crop = crop.resize((crop.width*2, crop.height*2), Image.LANCZOS)
crop.save('/mnt/d/AgentPrograms/wechat-bot/wsl/field-ready.png')
print(json.dumps({'saved': True}))
PY
