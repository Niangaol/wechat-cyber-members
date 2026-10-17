"""调试：当前会话气泡抽取到底抽到了什么。"""
import sys, json, time
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from wechat_ui import WeChatUI
from chat_navigator import ChatNavigator
from visual_parse import extract_messages
from ui_lease import ui_lease

STATE = Path.home() / ".local" / "state" / "wechat-bot"
cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
nav = ChatNavigator(ui)
with ui_lease(STATE):
    img = nav.switch_to("Agent 聊天测试群")
    print("title:", repr(nav.current_title(img)))
    bubbles = extract_messages(img)
    print("bubbles:", len(bubbles))
    for b in bubbles:
        print("  %-3s %-7s bbox=%-24s sig=%s text=%r" % (
            b.get('direction'), b.get('kind'), b.get('bbox'),
            str(b.get('signature'))[:12], str(b.get('text'))[:28]))
