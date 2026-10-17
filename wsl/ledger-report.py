import sqlite3
from pathlib import Path
p = Path.home()/'.local'/'state'/'wechat-bot'
stop = p/'STOP'
print('STOP present:', stop.exists(), repr(stop.read_text()) if stop.exists() else '')
db = sqlite3.connect(str(p/'ledger.sqlite'))
print('queue:', db.execute('SELECT state,count(*) FROM queue GROUP BY state').fetchall())
print('deliveries:', db.execute('SELECT count(*) FROM deliveries').fetchone()[0])
print('timeline:', db.execute('SELECT chat_key,direction,kind,count(*) FROM timeline GROUP BY 1,2,3').fetchall())
print('profiles:', db.execute('SELECT chat_key,kind,pending,learn_count FROM profiles').fetchall())
print('usage rows:', db.execute('SELECT count(*) FROM usage').fetchone()[0])
print('turns:', db.execute('SELECT chat_key,role,count(*) FROM turns GROUP BY 1,2').fetchall())
