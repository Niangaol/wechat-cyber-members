"""朋友圈互动（点赞+评论）人工确认/执行 CLI。

与 moment-release.py 同模式：人审令牌 + 安全闸 + 频率闸 + 坐标标定校验。
默认只跑闸门（dry-run）；只有 --execute 且批准令牌在位才真点 UI。
互动目标动态必须在当前信息流里能 OCR 核验到作者名，否则拒绝执行。

用法：
  python3 interact-release.py --list                  # 待互动清单/令牌/频率闸状态
  python3 interact-release.py --approve 3             # 批准 inbox id=3（写 APPROVE_INTERACT）
  python3 interact-release.py --revoke                # 撤回批准
  python3 interact-release.py --dry-run               # 跑完整闸门但不碰 UI
  python3 interact-release.py --execute [--id 3]      # 真执行（默认连赞带评）
  python3 interact-release.py --execute --no-like     # 只评论不点赞
  python3 interact-release.py --execute --no-comment  # 只点赞不评论

执行成功后标记 DONE（记 done_at，频率闸按它统计）并撤掉令牌；
执行前持久化 STARTED；失败/崩溃保留 STARTED/UNCERTAIN，禁止自动重试，需人工核对。
"""
import argparse
import hashlib
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]

from moment_interact import MomentInbox, InteractGuard, COMMENT_MAX  # noqa: E402
from moments_publisher import MomentsPublisher, PublisherError  # noqa: E402
from ui_lease import ui_lease, UILeaseBusy
from moment_release import load_coords  # noqa: E402
from moments_safe import sanitize_for_moment  # noqa: E402
from wechat_ui import WeChatUI, SafetyError, normalize  # noqa: E402

STATE = Path.home() / '.local' / 'state' / 'wechat-bot'
APPROVE_FILE = 'APPROVE_INTERACT'


def log(event, **kw):
    print(json.dumps({'event': event, **kw}, ensure_ascii=False), flush=True)


def open_inbox(db):
    inbox = MomentInbox(db)
    db.execute('CREATE TABLE IF NOT EXISTS interaction_attempts('
               ' mid INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,'
               ' attempt_key TEXT UNIQUE NOT NULL, state TEXT NOT NULL, started REAL NOT NULL)')
    # 全账本一次只准一个执行者；不确定结果也占位，不按超时自动释放。
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS interaction_single_active "
               "ON interaction_attempts((1)) WHERE state IN ('STARTED','UNCERTAIN')")
    db.commit()
    return inbox


def attempt_for(inbox, mid):
    if not inbox.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                            "AND name='interaction_attempts'").fetchone():
        return None
    return inbox.db.execute('SELECT attempt_key,state FROM interaction_attempts WHERE mid=?',
                            (mid,)).fetchone()


def claim_attempt(inbox, mid, like, comment):
    key = uuid.uuid4().hex
    try:
        inbox.db.execute('BEGIN IMMEDIATE')
        require_authorized(inbox, mid, like, comment)
        fingerprint = inbox.db.execute(
            'SELECT fingerprint FROM moment_inbox WHERE id=?', (mid,)).fetchone()[0]
        inbox.db.execute('INSERT INTO interaction_attempts VALUES(?,?,?,?,?)',
                         (mid, fingerprint, key, 'STARTED', time.time()))
        inbox.db.commit()  # 必须在任何 UI 动作之前耐久落盘。
    except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
        inbox.db.rollback()
        raise SafetyError('互动已尝试或有其他执行者，禁止重复执行') from e
    except BaseException:
        inbox.db.rollback()
        raise
    return key


def finish_attempt(inbox, mid, key):
    with inbox.db:
        cur = inbox.db.execute("UPDATE interaction_attempts SET state='DONE' "
                               "WHERE mid=? AND attempt_key=? AND state='STARTED'", (mid, key))
        if cur.rowcount != 1:
            raise SafetyError('尝试归属已变化，禁止标记成功')
        inbox.db.execute("UPDATE moment_inbox SET state='DONE',done_at=? WHERE id=?",
                         (time.time(), mid))


def token_path():
    return STATE / APPROVE_FILE


def payload_digest(inbox, mid):
    row = inbox.db.execute(
        'SELECT author,text,comment,fingerprint FROM moment_inbox WHERE id=?',
        (mid,)).fetchone()
    if not row:
        return None
    return hashlib.sha256(json.dumps(list(row), ensure_ascii=False).encode()).hexdigest()


def require_authorized(inbox, mid, like, comment, attempt_key=None):
    """磁盘授权每次重读；人审不能覆盖名单、暂停、安全与发布前置闸。"""
    if (STATE / 'STOP').exists():
        raise SafetyError('STOP 已启用，禁止互动')
    cfg = json.loads((ROOT / 'config' / 'resident.json').read_text())
    ic = cfg.get('interact') or {}
    if not ic.get('enabled'):
        raise SafetyError('互动授权已关闭')
    if approved_id(inbox, attempt_key) != mid:
        raise SafetyError('批准已撤回或内容发生变化，需重新确认')
    if inbox.db.execute("SELECT 1 FROM interaction_attempts WHERE state IN ('STARTED','UNCERTAIN') "
                        "AND attempt_key != ?", (attempt_key or '',)).fetchone():
        raise SafetyError('其他互动执行中或结果不确定，需人工核对')
    token = json.loads(token_path().read_text())
    if token.get('actions') != {'like': like, 'comment': comment}:
        raise SafetyError('互动动作与批准不一致，需重新确认')
    row = inbox.db.execute(
        'SELECT author,text,comment FROM moment_inbox WHERE id=?', (mid,)).fetchone()
    friends = ic.get('friends')
    if not isinstance(friends, list) or not normalize(row[0]) or normalize(row[0]) not in {
            normalize(f) for f in friends if isinstance(f, str)}:
        raise SafetyError('作者不在互动白名单内')
    sanitize_for_moment(row[1], 500)
    if comment:
        sanitize_for_moment(row[2] or '', COMMENT_MAX)
    try:
        published = inbox.db.execute(
            "SELECT 1 FROM moments WHERE state='PUBLISHED' AND published > 0 LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        published = None
    if not published:
        raise SafetyError('朋友圈发布链路尚无成功记录，禁止互动')
    ok, why = InteractGuard(ic).check(inbox)
    if not ok:
        raise SafetyError('频率闸拦住：' + why)


def approved_id(inbox, attempt_key=None):
    """读令牌并校验：格式错/条目不在 READY → None（视为未批准）。"""
    try:
        data = json.loads(token_path().read_text())
        mid = int(data['id'])
    except Exception:
        return None
    row = inbox.db.execute(
        'SELECT state FROM moment_inbox WHERE id=?', (mid,)).fetchone()
    attempt = attempt_for(inbox, mid)
    if attempt and not (attempt_key and attempt == (attempt_key, 'STARTED')):
        return None
    return mid if (row and row[0] == 'READY'
                   and data.get('digest') == payload_digest(inbox, mid)) else None


def approve(inbox, mid, like=True, comment=True):
    if attempt_for(inbox, mid):
        raise SafetyError('该动态已有执行尝试，禁止重新批准；请人工核对结果')
    row = inbox.db.execute(
        'SELECT state,comment FROM moment_inbox WHERE id=?', (mid,)).fetchone()
    if not row or row[0] != 'READY':
        raise SystemExit('id=%s 不是待互动条目（需 READY）' % mid)
    try:
        sanitize_for_moment(row[1] or '', COMMENT_MAX)
    except ValueError as e:
        raise SystemExit('评论未过安全闸，拒绝批准：%s' % e)
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = token_path().with_suffix('.tmp')
    tmp.write_text(json.dumps({'id': int(mid), 'approved_at': time.time(),
                               'digest': payload_digest(inbox, mid),
                               'actions': {'like': like, 'comment': comment}},
                              ensure_ascii=False))
    tmp.chmod(0o600)
    tmp.replace(token_path())
    return mid


def revoke():
    if token_path().exists():
        token_path().unlink()
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--list', action='store_true')
    g.add_argument('--approve', type=int, metavar='ID')
    g.add_argument('--revoke', action='store_true')
    g.add_argument('--dry-run', action='store_true')
    g.add_argument('--execute', action='store_true')
    ap.add_argument('--id', type=int, default=None, help='限定 inbox id（默认用令牌里的）')
    ap.add_argument('--no-like', action='store_true', help='只评论不点赞')
    ap.add_argument('--no-comment', action='store_true', help='只点赞不评论')
    args = ap.parse_args()
    if args.no_like and args.no_comment:
        log('aborted', reason='--no-like 和 --no-comment 不能同时给（那就没动作了）')
        return 2

    cfg = json.loads((ROOT / 'config' / 'resident.json').read_text())
    ic = cfg.get('interact') or {}
    if not ic.get('enabled'):
        log('aborted', reason='interact disabled in config')
        return 2

    STATE.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(STATE / 'ledger.sqlite')
    inbox = open_inbox(db)
    guard = InteractGuard(ic)
    active_key = None
    mid = None

    try:
        if args.list:
            rows = inbox.db.execute(
                "SELECT id,author,text,comment,state FROM moment_inbox"
                " WHERE state='READY' ORDER BY id").fetchall()
            ok, why = guard.check(inbox)
            log('interact_list', approved_id=approved_id(inbox),
                coords_calibrated=bool(load_coords(cfg, coords_file=ROOT / 'config' / 'moments-coords.json').get('interact_ui')),
                blocked_attempts=[{'id': r[0], 'state': r[1], 'started': r[2]} for r in
                    db.execute("SELECT mid,state,started FROM interaction_attempts "
                               "WHERE state IN ('STARTED','UNCERTAIN') ORDER BY started")],
                guard_ok=ok, guard_reason=why,
                max_per_day=guard.max_per_day,
                min_interval=guard.min_interval,
                items=[{'id': r[0], 'author': r[1], 'text': (r[2] or '')[:40],
                        'comment': r[3]} for r in rows])
            return 0

        if args.approve is not None:
            mid = approve(inbox, args.approve, not args.no_like, not args.no_comment)
            log('approved', id=mid, token=str(token_path()))
            return 0

        if args.revoke:
            log('revoked', removed=revoke())
            return 0

        # ---- 闸门（dry-run 与 execute 共用）----
        mid = approved_id(inbox)
        if mid is None:
            log('refused', reason='没有有效的互动批准令牌（APPROVE_INTERACT 缺失/失效）')
            return 4
        if args.id is not None and int(args.id) != mid:
            log('refused', reason='令牌指向 id=%s，与请求的 id=%s 不一致' % (mid, args.id))
            return 4
        row = inbox.db.execute(
            'SELECT author,comment,text FROM moment_inbox WHERE id=?', (mid,)).fetchone()
        author, comment, target_text = row[0], row[1] or '', row[2] or ''
        safe_comment = sanitize_for_moment(comment, COMMENT_MAX)
        ok, why = guard.check(inbox)
        if not ok:
            log('refused', reason='频率闸拦住：' + why)
            return 4
        require_authorized(inbox, mid, not args.no_like, not args.no_comment)
        coords = load_coords(cfg, coords_file=ROOT / 'config' / 'moments-coords.json')
        if not coords.get('interact_ui'):
            log('not_calibrated',
                reason='interact_ui 坐标未标定（config/moments-coords.json）',
                hint='先按 README「互动链路」标定 ···/评论框坐标')
            return 3
        payload = {'id': mid, 'author': author, 'comment': safe_comment,
                   'like': not args.no_like, 'comment_on': not args.no_comment}
        if args.dry_run:
            log('dry_run_ok', **payload)
            return 0

        # ---- 真执行：耐久占位后才允许进入 UI ----
        with ui_lease(STATE):
            active_key = claim_attempt(inbox, mid, not args.no_like, not args.no_comment)
            ui = WeChatUI(cfg)
            pub = MomentsPublisher(ui, coords)
            result = pub.like_and_comment(author, safe_comment,
                                          target_text=target_text,
                                          like=not args.no_like,
                                          comment=not args.no_comment,
                                          before_action=lambda: require_authorized(
                                              inbox, mid, not args.no_like, not args.no_comment, active_key))
            finish_attempt(inbox, mid, active_key)
            active_key = None
            revoke()
            log('interacted', **{**payload, **result})
            ok2, why2 = guard.check(inbox)
            log('after', guard_ok=ok2, guard_reason=why2,
                done_today=inbox.done_since(time.time() - 86400))
            return 0
    except UILeaseBusy as e:
        log('ui_busy', reason=str(e), attempted=False)
        return 7
    except NotImplementedError as e:
        log('not_calibrated', reason=str(e))
        return 3
    except PublisherError as e:
        log('interact_uncertain', reason=str(e),
            note='尝试已持久占位；禁止原样重试，请人工核对是否已点赞或已发评论')
        return 5
    except (SafetyError, ValueError) as e:
        log('safety_abort', reason=str(e))
        return 6
    finally:
        if active_key is not None:
            with db:
                db.execute("UPDATE interaction_attempts SET state='UNCERTAIN' "
                           "WHERE mid=? AND attempt_key=? AND state='STARTED'", (mid, active_key))
        db.close()


if __name__ == '__main__':
    sys.exit(main())
