#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
python3 - <<'PY'
import sqlite3
db = sqlite3.connect("/home/niangao/.local/state/wechat-bot/ledger.sqlite")
rows = db.execute("SELECT id,state,priority FROM queue").fetchall()
print("before:", rows)
# dry-run 脚本本该走的分支：finish(qid,'DRY_RUN')。崩溃发生在 finish 之前，这里补上。
db.execute("UPDATE queue SET state='DRY_RUN' WHERE state='PENDING'")
db.commit()
print("after:", db.execute("SELECT id,state,priority FROM queue").fetchall())
print("deliveries:", db.execute("SELECT count(*) FROM deliveries").fetchone()[0])
db.close()
PY
