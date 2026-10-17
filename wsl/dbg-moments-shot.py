"""只读：截朋友圈独立窗口，核对刚发布的那条。"""
import sys, json
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from wechat_ui import WeChatUI
from moment_release import load_coords
from moments_publisher import MomentsPublisher

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
ui = WeChatUI(cfg)
pub = MomentsPublisher(ui, load_coords(cfg))
wid = pub.find_moments_window()
print("moments_wid", wid)
if wid:
    shot = pub._shot()
    shot.save(ROOT + "/shots/moments-window.png")
    print("saved", shot.size)
