"""真机测图片发送：切目标会话 → send_image → 多张截图取证 → 报告结果。

用法：python3 wsl/dbg-sendimg.py [会话名] [图片路径]
默认：很帅的年糕 + outbox/first-post-image.jpg
"""
import sys, json, subprocess, time
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from wechat_ui import WeChatUI                       # noqa: E402
from chat_navigator import ChatNavigator             # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
target = sys.argv[1] if len(sys.argv) > 1 else "很帅的年糕"
img = sys.argv[2] if len(sys.argv) > 2 else ROOT + "/outbox/first-post-image.jpg"

ui = WeChatUI(cfg)
nav = ChatNavigator(ui)


def shot(tag):
    path = "%s/shots/imgtest-%s.png" % (ROOT, tag)
    subprocess.run(["import", "-window", "root", path], env=ui.env, timeout=30)
    print("shot ->", path)


print("目标会话:", target, "| 图片:", img, Path(img).stat().st_size, "bytes")
shot("0-before")
image = nav.switch_to(target)
print("已切到目标会话，界面 %s" % (image.size,))
time.sleep(0.5)
shot("1-switched")

t0 = time.time()
try:
    ui.send_image(img)
    print("send_image ✓ 用时 %.1fs" % (time.time() - t0))
except Exception as exc:                             # noqa: BLE001
    print("send_image ✗ %s: %s（用时 %.1fs）" % (type(exc).__name__, str(exc)[:180],
                                              time.time() - t0))
shot("2-immediately-after")
time.sleep(4)
shot("3-four-seconds-later")
print("完成")
