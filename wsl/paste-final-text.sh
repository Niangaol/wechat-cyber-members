#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
export DISPLAY=:99
# 重新生成文案文件（防 /tmp 被清）
python3 - <<'PY'
import sqlite3, sys
sys.path.insert(0, 'src')
from moments_safe import sanitize_for_moment
db = sqlite3.connect("/home/niangao/.local/state/wechat-bot/ledger.sqlite")
text = sanitize_for_moment(db.execute("SELECT text FROM moments WHERE id=2").fetchone()[0], 300)
open('/tmp/moment-text.txt','w').write(text)
print("TEXT_READY chars=%d" % len(text))
PY
printf '%s' "$(cat /tmp/moment-text.txt)" | xsel --clipboard --input
echo "clipboard len=$(xsel --clipboard --output | wc -c)"
echo "=== 焦点已在输入框，直接 ctrl+v ==="
timeout 10 xdotool key ctrl+v
sleep 1.5
import -window 14680150 /tmp/compose-final.png
cp /tmp/compose-final.png /mnt/d/AgentPrograms/wechat-bot/wsl/compose-final.png
echo ok
