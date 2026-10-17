"""Live batch OCR A/B: local tesseract vs one batched step-3.7-flash call on the same real bubbles.

Usage:
  python3 verify-batch-ocr.py                 # 3 rounds, re-capture each round
  python3 verify-batch-ocr.py --count 5       # 5 rounds
  python3 verify-batch-ocr.py --local-only    # local OCR only, no model quota spent
  python3 verify-batch-ocr.py --model-only    # skip local gate, whole batch via model

Prereq: WeChat logged in, target chat visible with a few test messages.
Output: one JSON per round, then a SUMMARY line (agreement rate, model rounds).
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from wechat_ui import WeChatUI            # noqa: E402
from visual_parse import extract_messages, ocr_bubbles, _local_best, needs_model_ocr, mentions_me  # noqa: E402
from multimodal import StepPlan           # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=3, help="number of capture/compare rounds")
    ap.add_argument("--local-only", action="store_true", help="local OCR only, no model call")
    ap.add_argument("--model-only", action="store_true", help="skip local gate, batch via model")
    ap.add_argument("--wait", type=float, default=0.0, help="seconds to sleep between rounds")
    args = ap.parse_args()

    cfg = json.loads((ROOT / "config" / "resident.json").read_text())
    aliases = cfg.get("mention_aliases") or [cfg.get("bot_name", "")]
    ui = WeChatUI(cfg)
    model = StepPlan(cfg)
    if not args.local_only and not model.key():
        print("NO_CREDENTIAL")
        return 2

    rounds = []
    for rnd in range(1, args.count + 1):
        im = ui.capture()
        bubbles = extract_messages(im)
        bboxes = [b["bbox"] for b in bubbles]
        if not bboxes:
            print(json.dumps({"round": rnd, "bubbles": 0, "note": "no bubbles detected"},
                             ensure_ascii=False), flush=True)
            if args.wait:
                time.sleep(args.wait)
            continue
        locals_ = [_local_best(ui, im, b) for b in bboxes]
        triggers = [needs_model_ocr(t, im, b, aliases) for t, b in zip(locals_, bboxes)]
        rec = {"round": rnd, "bubbles": len(bubbles), "local": locals_, "triggers": triggers}
        if args.local_only:
            rec["mode"] = "local_only"
            rec["final"] = locals_
        else:
            t0 = time.perf_counter()
            if args.model_only:
                final = ocr_bubbles(ui, im, bboxes, model=model, aliases=aliases)
                rec["mode"] = "model_only"
            else:
                final = ocr_bubbles(ui, im, bboxes, model=model, aliases=aliases) if any(triggers) else locals_
                rec["mode"] = "hybrid"
            rec["batch_model_seconds"] = round(time.perf_counter() - t0, 3)
            rec["final"] = final
            rec["changed"] = [i for i, (a, b) in enumerate(zip(locals_, final)) if a != b]
            rec["at_me_final"] = [mentions_me(t, aliases) for t in final]
        rounds.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)
        if args.wait and rnd < args.count:
            time.sleep(args.wait)

    agree = sum(1 for r in rounds for a, b in zip(r.get("local", []), r.get("final", [])) if a == b)
    total = sum(len(r.get("final", [])) for r in rounds)
    print(json.dumps({
        "SUMMARY": True,
        "rounds": len(rounds),
        "bubbles_total": total,
        "local_model_agree": agree,
        "agree_rate": round(agree / total, 3) if total else None,
        "rounds_using_model": sum(1 for r in rounds if r.get("mode") != "local_only"),
        "changed_total": sum(len(r.get("changed", [])) for r in rounds),
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
