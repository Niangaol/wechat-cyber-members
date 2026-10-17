import json, sys
from pathlib import Path
sys.path.insert(0, "/mnt/d/AgentPrograms/wechat-bot/src")
from wechat_ui import WeChatUI
from chat_navigator import ChatNavigator
from ui_lease import ui_lease

cfg = json.loads(Path("/mnt/d/AgentPrograms/wechat-bot/config/resident.json").read_text())
state = Path.home() / ".local/state/wechat-bot"
name, text = sys.argv[1], sys.argv[2]
ui = WeChatUI(cfg)
with ui_lease(state):
    nav = ChatNavigator(ui)
    nav.switch_to(name)
    after = ui.send_text(text, expected_chat=name)
    out = Path("/tmp") / ("sent-%s.png" % abs(hash(name)))
    after.save(str(out))
print(json.dumps({"sent_to": name, "chars": len(text), "evidence": str(out)}, ensure_ascii=False))
