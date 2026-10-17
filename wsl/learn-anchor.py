"""给「人机」群补一个列表像素锚点：OCR 读不动两字群名，但像素能认。

只在列表确实可见时用；保存前先验证 find_list_anchor 能唯一定位。
"""
import json, sys
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from wechat_ui import WeChatUI                                  # noqa: E402
import chat_anchors                                             # noqa: E402
from chat_navigator import find_chat_in_list                    # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ui.capture()
img.save(ROOT + "/shots/learn-source.png")

name = "人机"
row = img.crop((chat_anchors.LIST_X[0], 80, chat_anchors.LIST_X[1], 110))  # 第一行标题文字区
path = chat_anchors.anchor_path(name, "list")
path.parent.mkdir(parents=True, exist_ok=True)
row.save(path)
print("锚点写出:", path, row.size)

pos = chat_anchors.find_list_anchor(name, img)
print("find_list_anchor ->", pos)
print("find_chat_in_list ->", find_chat_in_list(ui, img, name))
