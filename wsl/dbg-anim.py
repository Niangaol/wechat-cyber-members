"""只读：确认聊天区两帧之间是否在持续变化（动图/视频会永不"稳定"）。"""
import sys, json, time
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
import numpy as np
from wechat_ui import WeChatUI, normalize
from chat_navigator import ChatNavigator

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
nav = ChatNavigator(ui)
img = nav.switch_to("Agent 聊天测试群")
crop = ui.chat_image(img)
time.sleep(1.2)
img2 = ui.capture()
crop2 = ui.chat_image(img2)
a = np.asarray(crop.convert("L"), dtype="int16")
b = np.asarray(crop2.convert("L"), dtype="int16")
print("sizes", a.shape, b.shape)
diff = np.abs(a - b) > 24
print("changed px ratio: %.4f (count %d)" % (diff.mean(), diff.sum()))
ys, xs = np.nonzero(diff)
if len(xs):
    print("changed bbox x=%d..%d y=%d..%d" % (xs.min(), xs.max(), ys.min(), ys.max()))
crop.save(ROOT + "/shots/anim-1.png")
crop2.save(ROOT + "/shots/anim-2.png")
