"""只读：私聊会话的气泡/图片抽取是否合理（新图片检测的第二个样本）。"""
import sys, json
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from wechat_ui import WeChatUI
from chat_navigator import ChatNavigator
from visual_parse import extract_messages, _panels, _photo_panels

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
nav = ChatNavigator(ui)
img = nav.switch_to("很帅的年糕")
img.save(ROOT + "/shots/dm-view.png")
print("title:", repr(nav.current_title(img)))
print("panels:", len(_panels(img, 283 + 64, img.height - 156)))
print("photos:", _photo_panels(img, 283 + 64, img.height - 156))
b = extract_messages(img)
print("extracted:", len(b))
for x in b:
    print("   ", x["direction"], x["bbox"])
