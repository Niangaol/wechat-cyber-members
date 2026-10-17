"""Read-only diagnosis of @ highlight colours in the current chat."""
import json, sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from wechat_ui import WeChatUI
from visual_parse import extract_messages, has_at_mention
ui = WeChatUI(json.loads((ROOT/'config'/'resident.json').read_text()))
im = ui.capture()
for m in extract_messages(im):
    if m['direction'] != 'in':
        continue
    x1, y1, x2, y2 = m['bbox']
    crop = im.crop((x1, y1, x2, y2))
    counts = Counter(crop.getdata())
    top = [(c, n) for c, n in counts.most_common(12)]
    print(json.dumps({'bbox': m['bbox'], 'has_at': has_at_mention(im, m['bbox']),
                      'top_colors': top}, ensure_ascii=False), flush=True)
