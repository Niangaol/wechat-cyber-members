#!/bin/bash
export DISPLAY=:99
echo "=== 点侧边栏测试群项（重新进入会话触发重绘）==="
# 测试群在列表第2行（File Transfer 上方）：窗口内约 (105, 120) → 绝对 (218, 151)
timeout 10 xdotool mousemove 218 151
timeout 10 xdotool click 1
sleep 3
import -window 14680080 /tmp/main-redraw.png
python3 - <<'PY'
import hashlib, json
a = hashlib.sha256(open('/tmp/main-redraw.png','rb').read()).hexdigest()[:12]
b = hashlib.sha256(open('/tmp/main-r32.png','rb').read()).hexdigest()[:12]
print(json.dumps({'after': a, 'before': b, 'changed': a != b}))
PY
cp /tmp/main-redraw.png /mnt/d/AgentPrograms/wechat-bot/wsl/main-redraw.png
