#!/bin/bash
export DISPLAY=:99
DW=$(timeout 10 xdotool search --name "^Open$" 2>/dev/null | head -1)
echo "dialog=$DW"
echo "=== XTEST 点 Open (912,586)，等 10 秒 ==="
timeout 10 xdotool mousemove 912 586
timeout 10 xdotool click 1
for i in 1 2 3 4 5; do
  sleep 2
  import -window root /tmp/wait-$i.png
done
python3 - <<'PY'
import hashlib, json
hs = [hashlib.sha256(open('/tmp/wait-%d.png'%i,'rb').read()).hexdigest()[:10] for i in range(1,6)]
print(json.dumps({'hashes': hs, 'all_same': len(set(hs))==1}))
PY
cp /tmp/wait-5.png /mnt/d/AgentPrograms/wechat-bot/wsl/screen-wait10.png
for w in $(timeout 10 xdotool search --name ".*" 2>/dev/null); do
  n=$(timeout 5 xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments|Open) echo "$w | $n";; esac
done
