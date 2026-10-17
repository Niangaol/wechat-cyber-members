#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
export DISPLAY=:99
# 1. 读草稿 #2 并过安全闸
python3 - <<'PY'
import json, sqlite3, sys
sys.path.insert(0, 'src')
from moments_safe import sanitize_for_moment
db = sqlite3.connect("/home/niangao/.local/state/wechat-bot/ledger.sqlite")
row = db.execute("SELECT id,text,image,state FROM moments WHERE id=2").fetchone()
print("draft:", row[0], row[3], "image:", bool(row[2]))
try:
    text = sanitize_for_moment(row[1], 300)
    open('/tmp/moment-text.txt', 'w').write(text)
    print("SAFE_OK chars=%d" % len(text))
    print("TEXT:", text)
except ValueError as e:
    print("SAFE_REJECT:", e)
    sys.exit(1)
PY
