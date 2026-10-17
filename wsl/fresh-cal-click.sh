#!/bin/bash
export DISPLAY=:99
cd /mnt/d/AgentPrograms/wechat-bot
W=$(xdotool search --name "^Open$" | head -1)
echo "geometry now: $(xdotool getwindowgeometry $W | tr '\n' ' ')"
# 1) 重新标定（同一进程内拿最新坐标）
CAL=$(python3 wsl/calibrate-file-dialog.py)
echo "$CAL"
FX=$(echo "$CAL" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['absolute']['file_path_input'][0])")
FY=$(echo "$CAL" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['absolute']['file_path_input'][1])")
echo "fresh field coord: $FX,$FY"
# 2) 立即点击 + 键入
xdotool windowactivate $W; sleep 0.4
xdotool mousemove $FX $FY click 1; sleep 0.5
xdotool type "QQQ"; sleep 0.6
import -window $W /tmp/dlg-fresh.png
python3 - <<'PY'
import json
from PIL import Image
im = Image.open('/tmp/dlg-fresh.png').convert('RGB')
crop = im.crop((90, 355, 560, 390))
crop = crop.resize((crop.width*3, crop.height*3), Image.LANCZOS)
crop.save('/mnt/d/AgentPrograms/wechat-bot/wsl/field-zoom3.png')
print(json.dumps({'saved': True}))
PY
