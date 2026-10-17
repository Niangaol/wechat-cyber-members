"""临时调试：会话列表定位为什么找不到目标（只读，不点击）。"""
import sys, json
sys.path.insert(0, "/mnt/d/AgentPrograms/wechat-bot/src")
from pathlib import Path
from wechat_ui import WeChatUI
from chat_navigator import ocr_tsv, merge_list_lines, find_chat_in_list, _line_matches

cfg = json.loads(Path("/mnt/d/AgentPrograms/wechat-bot/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ui.capture()
print("wid", ui.wid, "abs", getattr(ui, "last_abs", None), "size", img.size)
words = ocr_tsv(ui, img.crop((60, 60, 283, 555)))
print("merged lines:")
for cy, text, lx in merge_list_lines(words):
    print("   y=%6.1f x=%3d %r" % (cy, lx, text))
for name in ["很帅的年糕", "Agent 聊天测试群"]:
    print("==", name, "->", find_chat_in_list(ui, img, name))
