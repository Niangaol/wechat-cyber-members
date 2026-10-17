"""调试：切换失败重试路径到底走了哪一支。"""
import json, sys, os
sys.path[:0] = ["/mnt/d/AgentPrograms/wechat-bot", "/mnt/d/AgentPrograms/wechat-bot/src"]
from unittest.mock import patch
import test_integration as T

cfg = dict(T.BASE_CFG, watch_chats=[], group_whitelist=['家庭群'], max_send_retries=2)
r = T.make_resident(cfg)
ui, model = T.FakeWeChatUI(), T.FakeModel()
r.nav = T.FlakyNavigator(ui)
payload = json.dumps({'messages': [{'direction': 'in', 'kind': 'text', 'text': '在吗',
                                    'at_me': True, 'bbox': [80, 100, 200, 140],
                                    'signature': 'sig-1'}], 'want_search': False})
r.quota.enqueue('group:家庭群', 0, payload)
r.last_frame['group:家庭群'] = ui.chat_image(ui.capture())
with patch('resident.WeChatUI', return_value=ui), \
     patch('resident.StepPlan', return_value=model), \
     patch('resident.CONFIG', T.FakeConfig(cfg)), \
     patch('visual_parse.extract_messages', return_value=[]):
    for i in range(3):
        r.cycle(cfg)
        rows = r.db.execute("SELECT id, state FROM queue ORDER BY id").fetchall()
        print("after cycle", i + 1, "queue:", rows, "depth:", r.quota.depth(),
              "sent:", [t for t in ui.sent_texts if isinstance(t, tuple)])
print("nav switches:", r.nav.switches, "failed:", r.nav.failed)
