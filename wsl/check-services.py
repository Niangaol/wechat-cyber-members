"""Read-only service/window diagnostic."""
import json, subprocess
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from screen import list_x_windows
DISPLAY = ':99'
out = {}
for unit in ('wechat-stack', 'wechat-bot'):
    r = subprocess.run(['systemctl', '--user', 'show', unit, '-p', 'ActiveState', '-p', 'SubState'],
                       capture_output=True, text=True, timeout=15)
    out[unit] = dict(line.split('=', 1) for line in r.stdout.strip().splitlines() if '=' in line)
wins = [w for w in list_x_windows(DISPLAY) if 'wechat' in w['classes'].lower() or 'Weixin' in w['title']]
out['wechat_windows'] = [{'id': w['id'], 'title': w['title'], 'size': [w['w'], w['h']],
                          'pos': [w['x'], w['y']]} for w in wins]
out['main_window_ok'] = len([w for w in wins if w['title'] == 'Weixin' and w['w'] == 1021 and w['h'] == 740]) == 1
state = Path.home()/'.local'/'state'/'wechat-bot'
out['stop_file'] = (state/'STOP').exists()
out['stop_reason'] = (state/'STOP').read_text().strip() if (state/'STOP').exists() else ''
import sqlite3
db = sqlite3.connect(str(state/'ledger.sqlite'))
out['queue'] = db.execute('SELECT state,count(*) FROM queue GROUP BY state').fetchall()
out['deliveries'] = db.execute('SELECT count(*) FROM deliveries').fetchone()[0]
out['timeline_rows'] = db.execute('SELECT count(*) FROM timeline').fetchone()[0]
out['usage_rows'] = db.execute('SELECT count(*) FROM usage').fetchone()[0]
print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)
