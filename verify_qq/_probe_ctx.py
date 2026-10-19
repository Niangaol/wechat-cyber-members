import sys, tempfile, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'src'))
from memory import ChatMemory
import sqlite3
db = sqlite3.connect(':memory:')
m = ChatMemory(db)
m.record_turn('group:30003', 'user', '微信群的旧话')
m.record_turn('qq:10001:group:30003', 'user', 'QQ 的话')
m.note_messages('group:30003', 5, 'group', '微信群')
print('context_for(qq) 顶层键:', sorted(m.context_for('qq:10001:group:30003').keys()))
ctx = m.context_for('qq:10001:group:30003')
print('recent_turns 类型:', type(ctx['recent_turns']).__name__)
print('recent_turns[0]:', json.dumps(ctx['recent_turns'][0], ensure_ascii=False))
print('pending 键是否存在:', 'pending' in ctx)
print('profiles 表:', [d[0] for d in db.execute('SELECT * FROM profiles').description])
print('learn 签名:')
import inspect
print(' ', inspect.signature(m.learn))
print(' ', inspect.signature(m.learning_sample))
print(' ', inspect.signature(m.note_messages))
# merge_payloads 上限
sys.path.insert(0, str(ROOT / 'src'))
from quota import merge_payloads
a = json.dumps({'messages': [{'signature': 's%d' % i, 'text': 't%d' % i} for i in range(20)],
                'max_messages': 12}, ensure_ascii=False)
b = json.dumps({'messages': [{'signature': 'x%d' % i, 'text': 'x%d' % i} for i in range(20)],
                'max_messages': 12}, ensure_ascii=False)
merged = json.loads(merge_payloads(a, b))
print('merge_payloads 后 messages 条数:', len(merged['messages']))
