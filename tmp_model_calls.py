import sqlite3
p = '/home/niangao/.local/state/wechat-bot/ledger.sqlite'
db = sqlite3.connect(p)
cols = [r[1] for r in db.execute('PRAGMA table_info(model_calls)')]
print('cols:', cols)
for r in db.execute('SELECT * FROM model_calls ORDER BY id DESC LIMIT 5'):
    print(r)
