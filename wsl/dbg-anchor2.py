"""为什么刚存的标题模板立刻不匹配：逐项对比（新文件名，避免撞到旧脚本）。"""
import json, sys
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from PIL import Image                                          # noqa: E402
from wechat_ui import WeChatUI                                 # noqa: E402
import chat_anchors                                            # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ui.capture()
crop = img.crop(chat_anchors.TITLE_BOX).convert("RGB")
path = chat_anchors.anchor_path("很帅的年糕", "title")
print("模板:", path.name, path.stat().st_size, "字节")
with Image.open(path) as tpl:
    t = tpl.convert("RGB")
    tb, cb = t.tobytes(), crop.tobytes()
    print("模板 size/mode:", tpl.size, tpl.mode, "| crop:", crop.size, crop.mode)
    print("size 相等:", t.size == crop.size, "| 字节长度:", len(tb), len(cb))
    print("不同字节:", sum(1 for a, b in zip(tb, cb) if a != b) if len(tb) == len(cb) else "长度不同")
print("title_anchor_matches ->", chat_anchors.title_anchor_matches("很帅的年糕", img))
# 直接复刻一遍判断逻辑，看看哪一步 False
with Image.open(path) as tpl2:
    c2 = img.crop(chat_anchors.TITLE_BOX).convert("RGB")
    print("手工复刻:", tpl2.size == c2.size and tpl2.convert("RGB").tobytes() == c2.tobytes())
