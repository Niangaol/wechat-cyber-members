#!/bin/bash
export DISPLAY=:99
MW=14680150
echo "=== 剪贴板内容检查 ==="
xsel --clipboard --output | head -c 80; echo " [len=$(xsel --clipboard --output | wc -c)]"
echo "=== 测试1: --window 点击 + type ASCII ==="
timeout 10 xdotool mousemove --window $MW 285 53
timeout 10 xdotool click --window $MW 1
sleep 0.5
timeout 15 xdotool type --window $MW "TEST123"
sleep 1.0
import -window $MW /tmp/t1.png
python3 - <<'PY'
import hashlib, json
a = hashlib.sha256(open('/tmp/t1.png','rb').read()).hexdigest()[:12]
b = hashlib.sha256(open('/tmp/compose-typed2.png','rb').read()).hexdigest()[:12]
print(json.dumps({'t1': a, 'prev': b, 'changed': a != b}))
PY
echo "=== 测试2: XTEST 点击（不用 --window）+ type ==="
timeout 10 xdotool mousemove 638 167
sleep 0.3
timeout 10 xdotool click 1
sleep 0.5
timeout 15 xdotool type "ABCD"
sleep 1.0
import -window $MW /tmp/t2.png
python3 - <<'PY'
import hashlib, json
a = hashlib.sha256(open('/tmp/t2.png','rb').read()).hexdigest()[:12]
b = hashlib.sha256(open('/tmp/t1.png','rb').read()).hexdigest()[:12]
print(json.dumps({'t2': a, 't1': b, 'changed': a != b}))
PY
cp /tmp/t2.png /mnt/d/AgentPrograms/wechat-bot/wsl/compose-test2.png
