import json, sys
from pathlib import Path
sys.path.insert(0, "/mnt/d/AgentPrograms/wechat-bot/src")
from wechat_ui import WeChatUI

cfg = json.loads(Path("/mnt/d/AgentPrograms/wechat-bot/config/resident.json").read_text())
ui = WeChatUI(cfg)
img = ui.capture()
img.save("/tmp/probe-window.png")
text_zone = img.crop((283, 632, 890, 735))
text_zone.resize((text_zone.width * 2, text_zone.height * 2)).save("/tmp/probe-textzone.png")
report = {
    "ocr_text_zone": ui._draft_text(img),
    "clipboard_now": ui.clipboard_read()[:80],
    "last_abs": getattr(ui, "last_abs", None),
}
print(json.dumps(report, ensure_ascii=False))
