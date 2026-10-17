"""诊断：① 列表里"人机"为什么找不到 ② 很帅的年糕的像素模板为什么不再匹配。"""
import json, sys
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from PIL import Image                                        # noqa: E402
from wechat_ui import WeChatUI                              # noqa: E402
import chat_anchors                                          # noqa: E402
from chat_navigator import (ocr_tsv, merge_list_lines, _line_matches,   # noqa: E402
                            find_chat_in_list)

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ui.capture()
print("=== 列表行 ===")
words = ocr_tsv(ui, img.crop((60, 60, 283, 620)))
hits = 0
for cy, text, cx in merge_list_lines(words):
    t = str(text).strip()
    if not t:
        continue
    m = _line_matches("人机", t)
    hits += 1 if m else 0
    if m or "人" in t or "机" in t:
        print("  y=%-4d %-22r 匹配=%s" % (60 + cy, t, m))
print("命中行数 =", hits, "（要恰好 1 才算唯一）")
print("find_chat_in_list('人机') ->", find_chat_in_list(ui, img, "人机"))

print("=== 很帅的年糕 标题模板 ===")
header = img.crop((283, 20, 700, 61))
header.save(ROOT + "/shots/header-now.png")
anchor = Path(ROOT) / "config" / "target-title.png"
print("模板存在:", anchor.exists())
if anchor.exists():
    with Image.open(anchor) as tpl:
        same = tpl.convert("RGB").tobytes() == header.convert("RGB").tobytes()
    print("模板逐像素相等:", same)
print("title_anchor_matches ->", chat_anchors.title_anchor_matches("很帅的年糕", img))
print("标题 OCR 原文:", repr(ui.ocr(header, 7)))
print("窗口尺寸:", img.size, "| last_abs:", getattr(ui, "last_abs", None))
