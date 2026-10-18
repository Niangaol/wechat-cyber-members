#!/usr/bin/env python3
"""QQ 台账速查（lead 排查用）：打印最近的时间线/发送记录/模型调用。只读。"""
import sqlite3
import sys
from pathlib import Path

DB = Path.home() / ".local/state/qq-bot/qq.db"
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 5

db = sqlite3.connect(str(DB))
print("== timeline (最近 %d) ==" % LIMIT)
for row in db.execute("select id,kind,substr(text,1,90),image_path from timeline order by id desc limit ?", (LIMIT,)):
    print(" ", row)
print("== turns (最近 %d) ==" % LIMIT)
for row in db.execute("select role,substr(content,1,90) from turns order by id desc limit ?", (LIMIT,)):
    print(" ", row)
print("== send_log (最近 %d) ==" % LIMIT)
for row in db.execute("select chat_key,kind,state,substr(detail,1,40) from send_log order by id desc limit ?", (LIMIT,)):
    print(" ", row)
print("== 计数 ==")
print("  usage:", db.execute("select count(*) from usage").fetchone()[0],
      "| inbound:", db.execute("select count(*) from inbound").fetchone()[0],
      "| queue PENDING:", db.execute("select count(*) from queue where state='PENDING'").fetchone()[0])
