"""人工核对后清理"我们自己留下的草稿"（按目标会话 + 期望文案）。"""
import sys, json
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from wechat_ui import WeChatUI

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
chat = sys.argv[1] if len(sys.argv) > 1 else "Agent 聊天测试群"
expect = sys.argv[2] if len(sys.argv) > 2 else ""
ui = WeChatUI(cfg)
ui.verify_target(expected_chat=chat)
now = ui.input_text(expected_chat=chat)
print("input now:", repr(now[:120]))
if not now.strip():
    print("NO_DRAFT")
elif expect and now.strip() != expect.strip():
    print("DRAFT_NOT_OURS -> 不动")
else:
    print("cleared:", ui.clear_input(expected_chat=chat))
