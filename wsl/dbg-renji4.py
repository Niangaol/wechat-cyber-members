"""量一下「人机」群里头像到底在哪一列（逐列统计非背景像素）。"""
import json, sys
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from wechat_ui import WeChatUI                                 # noqa: E402
from chat_navigator import ChatNavigator                       # noqa: E402
import visual_parse as vp                                      # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
nav = ChatNavigator(ui)
img = nav.switch_to("人机")
print("窗口:", img.size)
print("列  x=290..440 每列"有内容的行数"（背景=237 灰）:")
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
        print("   x=%3d 有内容行 %3d" % (x, rows))
print("--- 用 avatar_rows 试各列 ---")
for x in (305, 340, 355, 370, 385, 400, 415, 430):
    print("   x=%3d -> %s" % (x, vp.avatar_rows(img, x)[:6]))
