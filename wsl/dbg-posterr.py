"""只读：验证失败红条检测（当前屏上还有两条 Photos not sent.）。"""
import sys, json
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from wechat_ui import WeChatUI
from moment_release import load_coords
from moments_publisher import MomentsPublisher

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
pub = MomentsPublisher(WeChatUI(cfg), load_coords(cfg))
print("post_error ->", repr(pub.post_error()))
