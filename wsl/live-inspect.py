import sys
from pathlib import Path
sys.path.insert(0,"/mnt/d/AgentPrograms/wechat-bot/src")
from wechat_ui import WeChatUI

cfg_path = Path("/mnt/d/AgentPrograms/wechat-bot/config/resident.json")
import json
cfg = json.loads(cfg_path.read_text())
ui = WeChatUI(cfg)
img = ui.capture()
img.save("/tmp/wechat-current.png")
draft_zone = img.crop((283, 605, 945, 654))
draft_zone = draft_zone.resize((draft_zone.width * 2, draft_zone.height * 2))
draft_zone.save("/tmp/wechat-draft-zone.png")
print("captured", list(img.size))
