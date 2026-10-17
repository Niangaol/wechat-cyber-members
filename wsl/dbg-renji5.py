"""量一下「人机」群里头像到底在哪一列。"""
import json, sys
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from wechat_ui import WeChatUI
from chat_navigator import ChatNavigator
import visual_parse as vp

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ChatNavigator(ui).switch_to("人机")
print("窗口:", img.size)
print("逐列统计（每列 10px 宽、行内至少 3 个非背景像素）:")
for x in range(290, 441, 10):
    rows = 0
    for y in range(78, img.height - 156):
        n = 0
        for dx in range(10):
            r, g, b = img.getpixel((x + dx, y))
            if abs(r-237) + abs(g-237) + abs(b-237) > 45:
                n += 1
        if n >= 3:
            rows += 1
    if rows:
        print("   x=%3d -> 有内容行 %3d" % (x, rows))
print("--- avatar_rows 各列 ---")
for x in (305, 340, 355, 370, 385, 400, 415, 430):
    print("   x=%3d ->" % x, vp.avatar_rows(img, x)[:8])
print("最终气泡数:", len(vp.extract_messages(img)))