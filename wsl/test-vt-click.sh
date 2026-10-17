#!/bin/bash
export DISPLAY=:99
MW=14680150
echo "=== 点 Visible To 行（绝对 638,474）==="
timeout 10 xdotool mousemove 638 474
timeout 10 xdotool click 1
sleep 1.5
import -window $MW /tmp/vt.png
cp /tmp/vt.png /mnt/d/AgentPrograms/wechat-bot/wsl/compose-vt.png
python3 - <<'PY'
import hashlib, json
a = hashlib.sha256(open('/tmp/vt.png','rb').read()).hexdigest()[:12]
b = hashlib.sha256(open('/tmp/compose-typed2.png','rb').read()).hexdigest()[:12]
print(json.dumps({'after_vt_click': a, 'before': b, 'changed': a != b}))
PY
echo "=== 焦点窗口 ==="
FW=$(timeout 5 xdotool getwindowfocus 2>/dev/null)
echo "focus=$FW name=[$(timeout 5 xdotool getwindowname $FW 2>/dev/null)]"
