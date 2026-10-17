"""只读：图片气泡为什么没被认出来。"""
import sys, json
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from wechat_ui import WeChatUI
from chat_navigator import ChatNavigator
from visual_parse import _panels, _photo_panels, avatar_rows

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
nav = ChatNavigator(ui)
img = nav.switch_to("Agent 聊天测试群")
img.save(ROOT + "/shots/photo-view.png")
sidebar = 283 if img.width == 1021 else 273
bottom = img.height - 156
print("panels:", _panels(img, sidebar+64, bottom))
print("photos:", _photo_panels(img, sidebar+64, bottom))
print("avatar rows in:", avatar_rows(img, sidebar+22))
print("avatar rows out:", avatar_rows(img, img.width-60))
