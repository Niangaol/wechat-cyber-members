"""只读侦察：把左侧会话列表的每一行 OCR 出来（有"人机"字样的会标出来）。不点击、不切换。"""
import sys
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
import json                                                    # noqa: E402
from wechat_ui import WeChatUI                                 # noqa: E402
from chat_navigator import ocr_tsv, merge_list_lines           # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ui.capture()
words = ocr_tsv(ui, img.crop((60, 60, 283, 620)))
seen = []
for cy, text, cx in merge_list_lines(words):
    text = str(text).strip()
    if text:
        mark = "  <== 像目标" if "人机" in text or "机" in text else ""
        print("y=%-4d %s%s" % (60 + cy, text, mark))
        seen.append(text)
print("--- 一共 %d 行 ---" % len(seen))
