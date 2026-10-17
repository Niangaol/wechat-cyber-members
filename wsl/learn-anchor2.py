"""给新群记一个列表像素锚点（长中英混排名字 OCR 认不准，只能靠像素）。"""
import json, sys
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from wechat_ui import WeChatUI
import chat_anchors
from chat_navigator import ocr_tsv, merge_list_lines, find_chat_in_list

NAME = "Vibe AI Lab 招新交流群"
cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ui.capture()
words = ocr_tsv(ui, img.crop((60, 60, 283, 620)))
row_y = None
for cy, text, cx in merge_list_lines(words):
    t = str(text)
    if "Vibe" in t or "vibe" in t or "招新" in t:
        row_y = 60 + cy
        print("候选行 y=%d %r" % (row_y, t))
if row_y is None:
    print("列表里找不到这个群"); sys.exit(1)
anchor = img.crop((chat_anchors.LIST_X[0], row_y - 10, chat_anchors.LIST_X[1], row_y + 20))
path = chat_anchors.anchor_path(NAME, "list")
path.parent.mkdir(parents=True, exist_ok=True)
anchor.save(path)
print("锚点:", path.name, anchor.size)
print("find_list_anchor ->", chat_anchors.find_list_anchor(NAME, img))
print("find_chat_in_list ->", find_chat_in_list(ui, img, NAME))