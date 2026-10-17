import sqlite3, time
p = '/home/niangao/.local/state/wechat-bot/ledger.sqlite'
db = sqlite3.connect(p)
print('ok=1 最近10条:')
for r in db.execute("SELECT id, datetime(created,'unixepoch','localtime'), error, latency_ms, prompt_tokens, completion_tokens FROM model_calls WHERE ok=1 ORDER BY id DESC LIMIT 10"):
    print(r)
print('按 error 汇总:')
for r in db.execute('SELECT ok, error, count(*), avg(latency_ms) FROM model_calls GROUP BY ok, error'):
    print(r)
