#!/bin/bash
set -e
cd /mnt/d/AgentPrograms/wechat-bot
python3 - <<'PY'
import json, sqlite3, sys, tempfile, shutil
from pathlib import Path
sys.path[:0] = ['/mnt/d/AgentPrograms/wechat-bot', '/mnt/d/AgentPrograms/wechat-bot/src']
from moment_release import MomentRelease
from moments import MomentComposer

STATE = Path('/home/niangao/.local/state/wechat-bot')
tmp = Path(tempfile.mkdtemp())
shutil.copy(STATE/'ledger.sqlite', tmp/'ledger.sqlite')
db = sqlite3.connect(tmp/'ledger.sqlite')
mc = {'max_chars': 300, 'with_image': True}
c = MomentComposer(db, None, mc)

class FakeUI:
    wid = '0x1'
    def run(self, args, data=None, timeout=12):
        return b''

coords = {'camera_icon': [100, 100], 'text_input': [200, 200], 'publish_button': [300, 300]}
rel = MomentRelease(db, FakeUI(), composer=c, state_dir=tmp, cfg=mc, coords=coords)
print('drafts:', [(d['id'], d['topic'], d['state']) for d in rel.drafts()])
d = rel.draft(2)
print('image_exists:', Path(d['image']).exists(), d['image'])
print('token:', rel.approve(2))
out = rel.publish(dry_run=True)
print('dry_run:', json.dumps(out, ensure_ascii=False))
print('state_after:', db.execute('SELECT state FROM moments WHERE id=2').fetchone())
print('token_left:', rel.approved_id())
print('DB_UNCHANGED:', db.execute("SELECT count(*) FROM moments WHERE state='PUBLISHED'").fetchone()[0] == 0)
db.close()
PY
