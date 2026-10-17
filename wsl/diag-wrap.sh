#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
python3 - <<'PY'
import json, sys, time, traceback
from pathlib import Path
ROOT = Path('/mnt/d/AgentPrograms/wechat-bot')
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from wechat_ui import WeChatUI
from visual_parse import extract_messages, ocr_bubbles, _local_best, needs_model_ocr
from multimodal import StepPlan

cfg = json.loads((ROOT/'config'/'resident.json').read_text())
aliases = cfg.get('mention_aliases') or [cfg.get('bot_name','')]
ui = WeChatUI(cfg)
model = StepPlan(cfg)
print('ocr_model =', cfg['step_plan'].get('ocr_model'))
for rnd in (1,2,3):
    im = ui.capture()
    bubbles = extract_messages(im)
    bboxes = [b['bbox'] for b in bubbles]
    loc = [_local_best(ui, im, b) for b in bboxes]
    trig = [needs_model_ocr(t, im, b, aliases) for t,b in zip(loc,bboxes)]
    t0=time.perf_counter()
    try:
        batch = model.ocr_bubbles_image(im, bboxes)
        err = None
    except Exception as e:
        batch = None
        err = type(e).__name__+': '+str(e)[:200]
    fin = ocr_bubbles(ui, im, bboxes, model=model, aliases=aliases)
    print(json.dumps({'round':rnd,'local':loc,'trig':trig,
        'direct_batch':batch,'direct_err':err,
        'ocr_bubbles_final':fin,
        'changed':[i for i,(a,b) in enumerate(zip(loc,fin)) if a!=b],
        'sec':round(time.perf_counter()-t0,2)}, ensure_ascii=False), flush=True)
PY
