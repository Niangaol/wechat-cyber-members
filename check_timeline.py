import sqlite3
from pathlib import Path
db = sqlite3.connect(str(Path.home()/'.local'/'state'/'wechat-bot'/'ledger.sqlite'))
try:
    n = db.execute('SELECT count(*) FROM timeline').fetchone()[0]
    print('timeline 条数:', n)
    for r in db.execute('SELECT chat_key,direction,kind,substr(text,1,24),image_path FROM timeline ORDER BY id DESC LIMIT 8'):
        print(' ', r)
except Exception as e:
    print('查询失败:', e)
media = Path.home()/'.local'/'state'/'wechat-bot'/'media'/'inbox'
files = list(media.rglob('*.png')) if media.exists() else []
print('气泡截图数:', len(files))
for f in files[-5:]:
    print(' ', f.relative_to(media.parent.parent), f.stat().st_size, 'bytes')
