"""诊断批量模型 OCR 的失败原因：直接调用 ocr_bubbles_image，打印原始返回/异常。

用法: python3 diag-batch-ocr.py [--times 5]
"""
import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]

from wechat_ui import WeChatUI            # noqa: E402
from visual_parse import extract_messages, _local_best, needs_model_ocr  # noqa: E402
from multimodal import StepPlan           # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--times', type=int, default=5)
    args = ap.parse_args()

    cfg = json.loads((ROOT / 'config' / 'resident.json').read_text())
    aliases = cfg.get('mention_aliases') or [cfg.get('bot_name', '')]
    ui = WeChatUI(cfg)
    model = StepPlan(cfg)
    if not model.key():
        print('NO_CREDENTIAL')
        return 2
    im = ui.capture()
    bubbles = extract_messages(im)
    bboxes = [b['bbox'] for b in bubbles]
    locals_ = [_local_best(ui, im, b) for b in bboxes]
    print(json.dumps({'bubbles': len(bubbles), 'local': locals_,
                      'triggers': [needs_model_ocr(t, im, b, aliases)
                                   for t, b in zip(locals_, bboxes)]}, ensure_ascii=False), flush=True)

    for i in range(1, args.times + 1):
        t0 = time.perf_counter()
        try:
            batch = model.ocr_bubbles_image(im, bboxes)
            print(json.dumps({'try': i, 'ok': True,
                              'seconds': round(time.perf_counter() - t0, 3),
                              'batch': batch}, ensure_ascii=False), flush=True)
        except Exception as e:
            print(json.dumps({'try': i, 'ok': False,
                              'seconds': round(time.perf_counter() - t0, 3),
                              'error': type(e).__name__,
                              'detail': str(e)[:300]}, ensure_ascii=False), flush=True)
            if args.times == 1:
                traceback.print_exc()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
