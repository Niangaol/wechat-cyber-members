"""调试：一轮连发两条为什么不生效。"""
import json, sys, sqlite3, tempfile
sys.path[:0] = ["/mnt/d/AgentPrograms/wechat-bot", "/mnt/d/AgentPrograms/wechat-bot/src"]
from pathlib import Path
from unittest.mock import patch
import test_integration as T

cfg = dict(T.BASE_CFG, watch_chats=[], group_whitelist=['Agent 聊天测试群'],
           concurrency={'max_watch_chats': 4, 'max_sends_per_cycle': 2, 'queue_yield_after': 3})
r = T.make_resident(cfg)
ui, model = T.FakeWeChatUI(), T.FakeModel()
r.nav = T.FakeNavigator(ui)
payload = json.dumps({'messages': [{'direction': 'in', 'kind': 'text', 'text': '在吗',
                                    'at_me': True, 'bbox': [80, 100, 200, 140],
                                    'signature': 'sig-1'}], 'want_search': False})
r.quota.enqueue('group:Agent 聊天测试群', 0, payload)
r.quota.enqueue('direct:很帅的年糕', 1, payload)
print('depth before', r.quota.depth())
with patch('resident.WeChatUI', return_value=ui), \
     patch('resident.StepPlan', return_value=model), \
     patch('resident.CONFIG', T.FakeConfig(cfg)), \
     patch('visual_parse.extract_messages', return_value=[]):
    r.cycle(cfg)
print('sent:', [t for t in ui.sent_texts if isinstance(t, tuple)])
print('depth after', r.quota.depth())
for row in r.db.execute('SELECT id,chat_key,priority,state FROM queue'):
    print('  queue', row)
print('deliveries', r.db.execute('SELECT count(*) FROM deliveries').fetchone()[0])
print('usage', r.db.execute('SELECT count(*) FROM usage').fetchone()[0])
print('switches', r.nav.switches)
