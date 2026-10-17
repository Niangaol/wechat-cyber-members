"""Fast baseline-only preflight for the controlled auto-reply test."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from wechat_ui import WeChatUI
from resident import Resident
cfg = json.loads((ROOT/'config'/'resident.json').read_text()); cfg['debounce_seconds'] = 0
ui = WeChatUI(cfg)
image = ui.verify_target(expected_chat='Agent 聊天测试群')
r = Resident()
try:
    r.observe_one(cfg, ui, None, 'Agent 聊天测试群', image)
    ck = 'group:Agent 聊天测试群'
    print(json.dumps({'baseline_visible': len(r.baselines.get(ck, [])),
                      'queue_pending': r.quota.depth(),
                      'timeline': len(r.memory.get_timeline(ck)),
                      'stop_file': (Path.home()/'.local'/'state'/'wechat-bot'/'STOP').exists()}), flush=True)
finally:
    r.db.close(); r.lock.close()
