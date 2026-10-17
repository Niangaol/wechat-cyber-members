"""实机核验：切换会话 + 标题核验（只切会话，不发任何消息）。"""
import sys, json, time
sys.path.insert(0, "/mnt/d/AgentPrograms/wechat-bot/src")
from pathlib import Path
from wechat_ui import WeChatUI, SafetyError
from chat_navigator import ChatNavigator
from chat_anchors import title_anchor_matches

cfg = json.loads(Path("/mnt/d/AgentPrograms/wechat-bot/config/resident.json").read_text())
ui = WeChatUI(cfg)
nav = ChatNavigator(ui)
for name in ["很帅的年糕", "Agent 聊天测试群"]:
    try:
        img = nav.switch_to(name)
        title = nav.current_title(img)
        print("OK  %-16s title=%r anchor=%s" % (name, title, title_anchor_matches(name, img)))
    except Exception as e:
        print("FAIL %-16s %s: %s" % (name, type(e).__name__, e))
    time.sleep(1)
img = ui.capture()
img.save("/mnt/d/AgentPrograms/wechat-bot/shots/after-switch.png")
print("saved after-switch.png")
