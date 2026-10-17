#!/bin/bash
export DISPLAY=:99
MW=14680193
echo "geometry: $(xdotool getwindowgeometry $MW | tr '\n' ' ')"
python3 - <<'PY'
import subprocess, json
info = subprocess.run(['xdotool','getwindowgeometry','14680193'],capture_output=True,text=True).stdout
pos = [l for l in info.splitlines() if 'Position' in l][0]
wx, wy = (int(v) for v in pos.split(':')[1].split('(')[0].strip().split(','))
print(json.dumps({'origin':[wx,wy]}))
# Cancel 按钮在窗口底部右侧：732x565 → 窗口内约 (530, 520)
print(json.dumps({'cancel_abs': [wx+530, wy+520]}))
PY
echo "=== 点 Cancel ==="
xdotool mousemove 860 660 click 1
sleep 1.5
import -window root /tmp/after-cancel.png
cp /tmp/after-cancel.png /mnt/d/AgentPrograms/wechat-bot/wsl/screen-after-cancel.png
echo "=== 窗口 ==="
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments|WeixinMention) echo "$w | $n";; esac
done
