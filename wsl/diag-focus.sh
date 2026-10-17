#!/bin/bash
export DISPLAY=:99
echo "=== 当前窗口 ==="
for w in $(xdotool search --name ".*" 2>/dev/null); do
  n=$(xdotool getwindowname $w 2>/dev/null)
  case "$n" in Weixin|Moments) echo "$w | $n";; esac
done
echo "=== 点输入框前焦点 ==="
FW=$(timeout 5 xdotool getwindowfocus 2>/dev/null); echo "focus=$FW [$(timeout 5 xdotool getwindowname $FW 2>/dev/null)]"
echo "=== XTEST 点输入框 (638,166) ==="
timeout 10 xdotool mousemove 638 166
timeout 10 xdotool click 1
sleep 0.8
echo "=== 点后焦点 ==="
FW2=$(timeout 5 xdotool getwindowfocus 2>/dev/null); echo "focus=$FW2 [$(timeout 5 xdotool getwindowname $FW2 2>/dev/null)]"
echo "=== 点后 type ASCII ==="
timeout 15 xdotool type "HELLO"
sleep 1.0
import -window root /tmp/dbg.png
cp /tmp/dbg.png /mnt/d/AgentPrograms/wechat-bot/wsl/screen-dbg.png
echo "=== 全屏哈希对比 ==="
python3 -c "
import hashlib
a=hashlib.sha256(open('/tmp/dbg.png','rb').read()).hexdigest()[:12]
b=hashlib.sha256(open('/tmp/esc.png','rb').read()).hexdigest()[:12]
print('changed:', a!=b, a, b)
"
