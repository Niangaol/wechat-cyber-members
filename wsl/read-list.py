"""Read only the visible session list; never interact or call a model."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from wechat_ui import WeChatUI
from chat_navigator import ocr_tsv
cfg = json.loads((ROOT / 'config' / 'resident.json').read_text())
ui = WeChatUI(cfg)
image = ui.capture()
print(json.dumps({'window': ui.wid, 'offset': ui.last_abs,
                  'words': ocr_tsv(ui, image.crop((60, 70, 283, 355)))}, ensure_ascii=False))
