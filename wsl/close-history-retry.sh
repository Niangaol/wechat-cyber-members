#!/bin/bash
export DISPLAY=:99
W=14682331
echo "geometry: $(xdotool getwindowgeometry $W | tr '\n' ' ')"
python3 - <<'PY'
import subprocess, json
info = subprocess.run(['xdotool','getwindowgeometry','14682331'],capture_output=True,text=True).stdout
pos = [l for l in info.splitlines() if 'Position' in l][0]
wx, wy = (int(v) for v in pos.split(':')[1].split('(')[0].strip().split(','))
# 573x729 窗口，关闭按钮在右上角：窗口内 (555, 15) → 绝对
print(json.dumps({'origin':[wx,wy], 'close_abs': [wx+555, wy+15]}))
PY
echo "=== 点关闭按钮 ==="
xdotool mousemove 946 118 click 1
sleep 1.5
xdotool search --name "^Chat History" 2>/dev/null && echo "STILL_OPEN" || echo "CLOSED"
echo "=== 重试点笑脸 (304,602) ==="
xdotool mousemove 304 602 click 1
sleep 2
echo "--- 新窗口? ---"
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments|Open|Chat*) echo "$w | $n";; esac
done
import -window root /tmp/smile2.png
cp /tmp/smile2.png /mnt/d/AgentPrograms/wechat-bot/wsl/smile-retry.png
