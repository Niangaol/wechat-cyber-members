import json, sqlite3
from pathlib import Path
STATE = Path.home() / '.local/state/wechat-bot'
out = {}
for name in ('status.json', 'baselines.json', 'APPROVE_MOMENT'):
    p = STATE / name
    if not p.exists():
        out[name] = 'missing'
        continue
    try:
        out[name] = json.loads(p.read_text())
    except Exception as e:
        out[name] = 'unreadable: ' + type(e).__name__
out['STOP_exists'] = (STATE / 'STOP').exists()
for name in ('PUBLISH_ATTEMPT', 'wechat-ui.lock'):
    out[name + '_exists'] = (STATE / name).exists()
db = STATE / 'ledger.sqlite'
if db.exists():
    con = sqlite3.connect('file:' + str(db) + '?mode=ro', uri=True)
    try:
        cols = ('id', 'state', 'topic', 'chars', 'image')
        out['moments'] = [dict(zip(cols, r)) for r in con.execute(
            'SELECT id,state,topic,length(text),image FROM moments ORDER BY id')]
        out['queue_counts'] = {s: n for s, n in con.execute(
            'SELECT state,count(*) FROM queue GROUP BY state')}
        out['usage_recent'] = [dict(zip(('created', 'priority'), r)) for r in con.execute(
            'SELECT created,priority FROM usage ORDER BY created DESC LIMIT 5')]
        out['tables'] = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    except Exception as e:
        out['ledger_error'] = type(e).__name__ + ': ' + str(e)[:120]
    finally:
        con.close()
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))