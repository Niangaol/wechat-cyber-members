"""Controlled first real auto-reply test against the real ledger.

Usage:
  python3 verify-auto-reply.py --dry-run   # full pipeline, never presses Return
  python3 verify-auto-reply.py --send      # really sends one reply to the test group

Requires the user to send one message into the group after the baseline is built.
"""
import argparse, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from wechat_ui import WeChatUI, SafetyError
from resident import Resident, chat_key_of
from multimodal import StepPlan
from output_safe import check_output, OutputSafetyError

GROUP = 'Agent 聊天测试群'
CK = 'group:' + GROUP


def log(event, **kw):
    print(json.dumps({'event': event, **kw}, ensure_ascii=False), flush=True)


def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--send', action='store_true')
    args = ap.parse_args()
    cfg = json.loads((ROOT / 'config' / 'resident.json').read_text())
    cfg['debounce_seconds'] = 0
    cfg['min_reply_seconds'] = 0

    if not cfg.get('automation', {}).get('enabled'):
        log('aborted', reason='automation disabled in config')
        return 2
    ui = WeChatUI(cfg)
    model = StepPlan(cfg)
    if not model.key():
        log('aborted', reason='no model credential')
        return 2
    stop = Path.home() / '.local' / 'state' / 'wechat-bot' / 'STOP'
    if args.send and stop.exists():
        log('aborted', reason='STOP file present; remove it before a real send')
        return 2
    if chat_key_of(cfg, GROUP) != CK:
        log('aborted', reason='group not authorized by current policy')
        return 2

    r = Resident()
    try:
        leftovers = r.db.execute("SELECT state,count(*) FROM queue GROUP BY state").fetchall()
        log('ledger_ready', state_dir=str(r.stop.parent), queue=leftovers,
            deliveries=r.db.execute('SELECT count(*) FROM deliveries').fetchone()[0])
        if any(state == 'PENDING' for state, _ in leftovers):
            log('aborted', reason='unexpected PENDING task from an earlier run')
            return 2
        image = ui.verify_target(expected_chat=GROUP)
        r.observe_one(cfg, ui, model, GROUP, image)
        log('baseline', visible=len(r.baselines.get(CK, [])))
        if CK not in r.baselines:
            log('aborted', reason='baseline not stable')
            return 2

        deadline = time.monotonic() + 180
        enqueued = None
        while time.monotonic() < deadline:
            time.sleep(2)
            image = ui.verify_target(expected_chat=GROUP)
            if r.observe_one(cfg, ui, model, GROUP, image):
                enqueued = r.quota.peek()
                break
        if not enqueued:
            log('watch_expired', model_calls=0, sent=0)
            return 3
        qid, ck, priority, _, payload = enqueued
        task = json.loads(payload)
        log('enqueued', qid=qid, priority=priority,
            kinds=[m.get('kind') for m in task['messages']])

        # ---- generation stage (identical code path to production) ----
        fresh = task['messages']
        ctx = r.memory.context_for(ck)
        t0 = time.perf_counter()
        raw = model.reply(fresh, ctx.get('recent_turns', []), [], chat_context=ctx)
        try:
            reply = check_output(raw, cfg['reply_max_chars'])
        except OutputSafetyError as e:
            r.quota.finish(qid, 'UNSAFE_REPLY')
            log('blocked_safety', reason=type(e).__name__, sent=0)
            return 4
        log('generated', seconds=round(time.perf_counter() - t0, 3),
            chars=len(reply), preview=reply[:60], quota_calls=1)

        if args.dry_run:
            # dry-run 只验证到"生成"为止：不碰发送前的 STOP/目标核验，也不按 Return
            log('dry_run_complete', would_send=reply, sent=0, stop_file_present=stop.exists())
            r.quota.finish(qid, 'DRY_RUN')
            return 0

        # ---- pre-send verification identical to production ----
        r.latest_send_config(ck)
        if ui.chat_image(ui.verify_target(expected_chat=GROUP)).tobytes() != \
                ui.chat_image(image).tobytes():
            r.quota.finish(qid, 'CHANGED')
            log('aborted', reason='chat changed before send')
            return 5

        # ---- real send ----
        before = ui.chat_image(ui.capture()).tobytes()
        after = ui.send_text(reply, expected_chat=GROUP,
                             expected_guard=lambda: r.latest_send_config(ck))
        r.quota.finish(qid, 'SUBMITTED')
        r.db.execute('INSERT INTO deliveries(created,state,digest) VALUES(?,?,?)',
                     (time.time(), 'SUBMITTED', __import__('hashlib').sha256(payload.encode()).hexdigest()))
        r.db.commit()
        r.memory.record_turn(ck, 'assistant', reply)
        r.memory.add_timeline(ck, 'out', 'text', reply)
        time.sleep(2)
        confirmed = ui.chat_image(ui.capture()).tobytes() != before
        deliveries = r.db.execute('SELECT count(*) FROM deliveries').fetchone()[0]
        out_rows = r.db.execute("SELECT count(*) FROM timeline WHERE chat_key=? AND direction='out'", (ck,)).fetchone()[0]
        log('sent', text=reply, bubble_visible=confirmed,
            deliveries=deliveries, out_timeline=out_rows,
            input_box_clean=not __import__('re').sub(r'\s+', '', ui.ocr(after.crop((283, 605, 945, 654)), 6)))
        return 0 if confirmed and deliveries and out_rows else 6
    finally:
        r.db.close()
        r.lock.close()


if __name__ == '__main__':
    sys.exit(main())
