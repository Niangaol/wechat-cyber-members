"""Live A/B: local tesseract vs step-3.7-flash on the same real bubbles."""
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from wechat_ui import WeChatUI
from visual_parse import extract_messages, ocr_bubble, _local_best, needs_model_ocr, mentions_me
from multimodal import StepPlan
cfg = json.loads((ROOT/'config'/'resident.json').read_text())
aliases = cfg.get('mention_aliases') or [cfg.get('bot_name', '')]
ui = WeChatUI(cfg)
model = StepPlan(cfg)
if not model.key():
    print('NO_CREDENTIAL'); raise SystemExit(2)
im = ui.capture()
rows = []
for m in extract_messages(im):
    local = _local_best(ui, im, m['bbox'])
    need = needs_model_ocr(local, im, m['bbox'], aliases)
    row = {'bbox': m['bbox'], 'local': local, 'needs_model': need}
    if need:
        t = time.perf_counter()
        row['model'] = ocr_bubble(ui, im, m['bbox'], model=model, aliases=aliases)
        row['model_seconds'] = round(time.perf_counter()-t, 3)
    rows.append(row)
print(json.dumps({'aliases': aliases,
                  'at_me_local': [mentions_me(r['local'], aliases) for r in rows],
                  'at_me_final': [mentions_me(r.get('model', r['local']), aliases) for r in rows],
                  'rows': rows}, ensure_ascii=False, indent=1), flush=True)
