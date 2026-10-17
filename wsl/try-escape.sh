#!/bin/bash
export DISPLAY=:99
echo "=== 试 Escape 关闭 ==="
timeout 10 xdotool key --window 14680193 --clearmodifiers Escape
sleep 1.5
import -window root /tmp/esc.png
python3 - <<'PY'
import hashlib, json
a = hashlib.sha256(open('/tmp/esc.png','rb').read()).hexdigest()[:12]
b = hashlib.sha256(open('/tmp/after-cancel.png','rb').read()).hexdigest()[:12]
print(json.dumps({'after_esc': a, 'before': b, 'changed': a != b}))
PY
echo "=== Mention 窗口还在? ==="
xdotool search --name "^WeixinMention$" 2>/dev/null || echo "GONE"
