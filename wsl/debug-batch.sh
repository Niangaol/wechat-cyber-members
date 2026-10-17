#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
python3 - <<'PY'
import sys
sys.path.insert(0, 'src'); sys.path.insert(0, '.')
from test_ocr_pipeline import FakeUI, bubble, STACKED
from visual_parse import _local_best, needs_model_ocr, ocr_bubbles
ALIASES = ['年糕Agent', '年糕']
ui = FakeUI(['神了']*4 + ['ASAE 3']*4 + ['神了']*4)
img = bubble(height=300)
for b in STACKED:
    t = _local_best(ui, img, b)
    print('bbox', b, 'local=', repr(t), 'needs=', needs_model_ocr(t, img, b, ALIASES), 'calls=', ui.calls)
print('--- batch')
class M:
    def ocr_bubbles_image(self, image, bboxes):
        print('MODEL CALLED with', len(bboxes), 'bboxes')
        return {0: '神了', 1: '怎么回事', 2: '你 tm 是谁？'}
ui2 = FakeUI(['神了']*4 + ['ASAE 3']*4 + ['神了']*4)
print('result:', ocr_bubbles(ui2, img, STACKED, model=M(), aliases=ALIASES))
PY
