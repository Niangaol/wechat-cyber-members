"""验证批量模型 OCR 真的修好了：同一屏气泡，本地 vs 模型纠正 对照。"""
import json, sys
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
import sqlite3                                                # noqa: E402
from wechat_ui import WeChatUI                                # noqa: E402
from chat_navigator import ChatNavigator                      # noqa: E402
import visual_parse as vp                                     # noqa: E402
from multimodal import StepPlan                               # noqa: E402
from resident import _QuotedOCR, PRIORITY_GROUP_PLAIN         # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ChatNavigator(ui).switch_to("人机")
bubbles = vp.extract_messages(img)
bboxes = [tuple(b['bbox']) for b in bubbles]
print("气泡数:", len(bboxes))

local = vp.ocr_bubbles(ui, img, bboxes, model=None)
print("--- 只有本地 OCR ---")
for t in local:
    print("   ", repr(t[:60]))

class Stub:
    def spend(self, *a, **k):
        pass

plan = StepPlan(cfg, sqlite3.connect(":memory:"))
fixed = vp.ocr_bubbles(ui, img, bboxes, model=_QuotedOCR(Stub(), cfg, plan), aliases=cfg.get('mention_aliases'), force=True)
print("--- 模型批量纠正后 ---")
for t in fixed:
    print("   ", repr(t[:60]))
print("有变化的气泡数:", sum(1 for a, b in zip(local, fixed) if a != b))
