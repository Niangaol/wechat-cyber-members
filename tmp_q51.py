import sqlite3
p = '/home/niangao/.local/state/wechat-bot/ledger.sqlite'
db = sqlite3.connect(p)
for r in db.execute('SELECT id, chat_key, state, datetime(created,"unixepoch","localtime") FROM queue ORDER BY id DESC LIMIT 4'):
    print(r)
