#!/bin/bash
python3 /mnt/d/AgentPrograms/wechat-bot/wsl/ledger-report.py 2>&1 | head -12
echo "=== queue detail ==="
python3 - <<'PY'
import sqlite3, json
db = sqlite3.connect("/home/niangao/.local/state/wechat-bot/ledger.sqlite")
for qid, st, pr, payload in db.execute("SELECT id,state,priority,payload FROM queue ORDER BY id").fetchall():
    task = json.loads(payload)
    print("qid", qid, st, "priority", pr)
    for m in task.get("messages", []):
        print("   ", m.get("direction"), m.get("kind"), repr(m.get("text", "")[:60]), "at_me=", m.get("at_me"))
print("=== timeline (最近8条) ===")
for row in db.execute("SELECT chat_key,direction,kind,text FROM timeline ORDER BY id DESC LIMIT 8").fetchall():
    print("timeline:", row[0], row[1], row[2], repr(str(row[3])[:50]))
PY
