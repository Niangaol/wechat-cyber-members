"""实机验证：滚到顶这一步不会出错、也不影响后续切换。"""
import sys, json
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from wechat_ui import WeChatUI
from chat_navigator import ChatNavigator

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
nav = ChatNavigator(ui)
ui.capture()
after = nav.scroll_list_top()
print("scroll ok, size:", after.size)
img = nav.switch_to("Agent 聊天测试群")
print("switch after scroll:", repr(nav.current_title(img)))
