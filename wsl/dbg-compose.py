"""实验：打开朋友圈编辑页（带一张小图），并截图看缩略图上有没有删除入口。"""
import sys, json, time, io
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from PIL import Image
from wechat_ui import WeChatUI
from moment_release import load_coords
from moments_publisher import MomentsPublisher

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
pub = MomentsPublisher(ui, load_coords(cfg))
pub.moments_wid = None
wid = pub.open_moments_panel()
print("moments wid:", wid)
pub._click("camera_icon")
time.sleep(2)
dlg = pub._wait_window("^Open$", 10)
print("dialog:", dlg)
if not dlg:
    raise SystemExit("no dialog")
pub._dialog_type_path(dlg, sys.argv[1] if len(sys.argv) > 1 else "/home/niangao/.local/state/wechat-bot/media/oc-intro.jpg")
pub._sh(["xdotool", "key", "--clearmodifiers", "Return"])
pub._wait_window_gone("^Open$", 15)
time.sleep(3)
shot = pub._shot()
shot.save(ROOT + "/shots/compose-open.png")
print("compose shot:", shot.size)
