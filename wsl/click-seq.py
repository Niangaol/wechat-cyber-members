import json, sys, time
from pathlib import Path
sys.path.insert(0, "/mnt/d/AgentPrograms/wechat-bot/src")
from wechat_ui import WeChatUI

cfg = json.loads(Path("/mnt/d/AgentPrograms/wechat-bot/config/resident.json").read_text())
ui = WeChatUI(cfg)
ui.capture()
ui.run(["xdotool", "windowactivate", ui.wid])
ui.run(["xdotool", "windowfocus", ui.wid])
time.sleep(0.6)
ax, ay = ui.last_abs
before = ui.capture()
before.save("/tmp/seq-0.png")
ui.run(["xdotool", "mousemove", str(ax + 33), str(ay + 251)])
time.sleep(0.3)
ui.run(["xdotool", "click", "1"])
for i in range(1, 7):
    time.sleep(2)
    ui.capture().save("/tmp/seq-%d.png" % i)
out = ui.run(["xdotool", "search", "--onlyvisible", "--class", "wechat"]).decode()
print(json.dumps({"windows": out.split()}, ensure_ascii=False))
