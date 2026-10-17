"""实机验证：自救动作（拉前台 + Esc）不会出错、也不会弄乱界面。"""
import sys, json
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from wechat_ui import WeChatUI
from chat_navigator import ChatNavigator

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
nav = ChatNavigator(ui)
img = ui.capture()
print("before:", repr(nav.current_title(img)), img.size)
after = ui.activate()
print("after :", repr(nav.current_title(after)), after.size)
img2 = nav.switch_to("Agent 聊天测试群")
print("switch after activate ok:", repr(nav.current_title(img2)))
