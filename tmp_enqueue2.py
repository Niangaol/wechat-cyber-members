import sqlite3, json, time
p = '/home/niangao/.local/state/wechat-bot/ledger.sqlite'
db = sqlite3.connect(p)
print('pending profiles:')
for r in db.execute('SELECT chat_key, pending FROM profiles'):
    print(' ', r)
payload = json.dumps({'messages': [{'direction': 'in', 'kind': 'text',
                                     'text': '发个图看看你长什么样',
                                     'signature': 'selftest-%d' % int(time.time())}]},
                     ensure_ascii=False)
cur = db.execute("INSERT INTO queue(chat_key,priority,created,payload,state) VALUES(?,?,?,?,?)",
                 ('group:Agent 聊天测试群', 0, time.time(), payload, 'PENDING'))
db.commit()
print('enqueued id=', cur.lastrowid)
