"""Live read-only check of bubble-level OCR quality and @ detection."""
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from wechat_ui import WeChatUI
from visual_parse import extract_messages, classify, ocr_bubble, mentions_me
cfg = json.loads((ROOT/'config'/'resident.json').read_text())
aliases = cfg.get('mention_aliases') or [cfg.get('bot_name', '')]
ui = WeChatUI(cfg)
im = ui.capture()
t = time.perf_counter()
rows = []
for m in extract_messages(im):
    text = ocr_bubble(ui, im, m['bbox'])
    rows.append({'direction': m['direction'], 'bbox': m['bbox'], 'text': text,
                 'kind': classify(im.crop(m['bbox']), text),
                 'at_me': mentions_me(text, aliases)})
print(json.dumps({'seconds': round(time.perf_counter()-t, 3), 'aliases': aliases,
                  'messages': rows}, ensure_ascii=False), flush=True)
