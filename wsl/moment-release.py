"""朋友圈草稿确认/发布 CLI（人审令牌 + 安全闸 + 坐标标定校验）。

用法：
  python3 moment-release.py --list                 # 看草稿和当前批准状态
  python3 moment-release.py --approve 3            # 批准 id=3 的草稿（写 APPROVE_MOMENT）
  python3 moment-release.py --revoke               # 撤回批准
  python3 moment-release.py --dry-run              # 跑完整闸门，但不碰 UI（上线前自证）
  python3 moment-release.py --open-panel           # 点开朋友圈面板并截图（需标定 moments_icon）
  python3 moment-release.py --publish [--id 3]     # 真正发布已批准的草稿

提交成功后才写 PUBLISHED；若 PUBLISH_ATTEMPT 留存则结果不确定，禁止重试，需人工核对。
"""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]

from moment_release import MomentRelease, ReleaseError, STATE, load_coords  # noqa: E402
from moments import MomentComposer  # noqa: E402
from moments_publisher import PublisherError  # noqa: E402
from wechat_ui import WeChatUI, SafetyError  # noqa: E402


def log(event, **kw):
    print(json.dumps({'event': event, **kw}, ensure_ascii=False), flush=True)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--list', action='store_true')
    g.add_argument('--approve', type=int, metavar='ID')
    g.add_argument('--revoke', action='store_true')
    g.add_argument('--dry-run', action='store_true')
    g.add_argument('--open-panel', action='store_true')
    g.add_argument('--publish', action='store_true')
    ap.add_argument('--id', type=int, default=None, help='限定草稿 id（默认用批准令牌里的）')
    args = ap.parse_args()

    cfg = json.loads((ROOT / 'config' / 'resident.json').read_text())
    mc = cfg.get('moments') or {}
    if not mc.get('enabled'):
        log('aborted', reason='moments disabled in config')
        return 2

    STATE.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(STATE / 'ledger.sqlite')
    db.execute('CREATE TABLE IF NOT EXISTS moments('
               ' id INTEGER PRIMARY KEY, created REAL, topic TEXT, seed TEXT,'
               ' text TEXT, image TEXT, state TEXT, published REAL)')
    db.commit()
    composer = MomentComposer(db, None, mc)
    coords = load_coords(cfg)
    ui = WeChatUI(cfg)
    rel = MomentRelease(db, ui, composer=composer, coords=coords, cfg=mc)

    try:
        if args.list:
            rows = db.execute("SELECT id,topic,state,length(text),image,created FROM moments"
                              " ORDER BY created DESC LIMIT 20").fetchall()
            log('drafts', approved_id=rel.approved_id(), coords=sorted(coords),
                moments=[{'id': r[0], 'topic': r[1], 'state': r[2], 'chars': r[3],
                          'image': bool(r[4]), 'created': r[5]} for r in rows])
            for d in rel.drafts():
                log('draft', id=d['id'], topic=d['topic'], text=d['text'], image=d['image'])
            return 0

        if args.approve is not None:
            path = rel.approve(args.approve)
            d = rel.draft(args.approve)
            log('approved', id=args.approve, token=str(path), text=d['text'], image=d['image'])
            return 0

        if args.revoke:
            log('revoked', removed=rel.revoke())
            return 0

        if args.open_panel:
            shot = rel.open_moments_panel()
            out = Path('/tmp/moments-panel.png')
            shot.save(out)
            log('panel_open', shot=str(out), size=list(shot.size))
            return 0

        if args.dry_run:
            r = rel.publish(args.id, dry_run=True)
            log('dry_run_ok', **r)
            return 0

        # ---- 真发布 ----
        r = rel.publish(args.id)
        log('published', **r)
        row = db.execute("SELECT count(*) FROM moments WHERE state='PUBLISHED'").fetchone()[0]
        log('after', published_total=row, next_due_days=mc.get('min_days'), approve_left=rel.approved_id())
        return 0
    except NotImplementedError as e:
        log('not_calibrated', reason=str(e),
            hint='先跑 wsl/calibrate-moments.py 标定坐标并写入 config/moments-coords.json')
        return 3
    except ReleaseError as e:
        log('refused', reason=str(e))
        return 4
    except PublisherError as e:
        log('publish_uncertain', reason=str(e),
            note='草稿保持 DRAFT，批准令牌保留，可原样重试')
        return 5
    except SafetyError as e:
        log('safety_abort', reason=str(e))
        return 6
    finally:
        db.close()


if __name__ == '__main__':
    sys.exit(main())
