import json, sys, time
from pathlib import Path
sys.path.insert(0, "/mnt/d/AgentPrograms/wechat-bot/src")
from wechat_ui import WeChatUI

cfg = json.loads(Path("/mnt/d/AgentPrograms/wechat-bot/config/resident.json").read_text())
ui = WeChatUI(cfg)
ui.capture()  # wid + last_abs + 固定几何校验
ui.run(["xdotool", "windowactivate", ui.wid])
ui.run(["xdotool", "windowfocus", ui.wid])
time.sleep(0.6)
ax, ay = ui.last_abs
ui.run(["xdotool", "mousemove", str(ax + 33), str(ay + 251)])
time.sleep(0.3)
ui.run(["xdotool", "click", "1"])
found = None
for i in range(25):
    time.sleep(1.0)
    out = ui.run(["xdotool", "search", "--onlyvisible", "--class", "wechat"]).decode()
    for wid in out.split():
        info = ui.run(["xdotool", "getwindowgeometry", "--shell", wid]).decode()
        import re
        w = re.search(r"WIDTH=(\d+)", info)
        h = re.search(r"HEIGHT=(\d+)", info)
        if w and h and 560 <= int(w.group(1)) <= 590 and 560 <= int(h.group(1)) <= 760:
            found = wid
            break
    if found:
        break
name = ui.run(["xdotool", "getwindowname", found]).decode().strip() if found else ""
print(json.dumps({"found": found, "name": name, "waited": i + 1}, ensure_ascii=False))
