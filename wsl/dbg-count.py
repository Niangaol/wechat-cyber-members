"""只读：对比"抽到几个气泡"和"画面里实际有几个气泡"。"""
import sys, json
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from wechat_ui import WeChatUI
from chat_navigator import ChatNavigator
from visual_parse import extract_messages, _panels

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
nav = ChatNavigator(ui)
img = nav.switch_to("Agent 聊天测试群")
img.save(ROOT + "/shots/count-view.png")
print("title:", repr(nav.current_title(img)))
print("panels(白/绿气泡底):", len(_panels(img, 283 + 64, img.height - 156)))
bubbles = extract_messages(img)
print("extracted:", len(bubbles))
for b in bubbles:
    print("   bbox", b["bbox"])
