#!/usr/bin/env python3
"""一键上线自检：把所有离线可验的闸门跑一遍，最后给一张表。

用法：
    DISPLAY=:99 python3 wsl/acceptance.py            # 不含单元测试（快）
    DISPLAY=:99 python3 wsl/acceptance.py --tests    # 连 370 项单元测试一起跑

退出码 0 = 全过；非 0 = 有 FAIL（上面会写明哪一节）。
"""
import json, os, sqlite3, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
STATE = Path.home() / '.local' / 'state' / 'wechat-bot'
RESULTS = []


class SkipCheck(Exception):
    """这项现在不适用（比如"有没有待审草稿"）——不算失败，但要在表里如实写出来。"""


def check(name, fn):
    try:
        detail = fn() or ''
    except SkipCheck as exc:
        RESULTS.append((None, name, str(exc)))
    except Exception as exc:                       # noqa: BLE001
        RESULTS.append((False, name, '%s: %s' % (type(exc).__name__, str(exc)[:120])))
    else:
        RESULTS.append((True, name, detail))


# ---------- 1. 环境 ----------
def env_services():
    bad = []
    for unit in ('wechat-stack', 'wechat-bot'):
        r = subprocess.run(['systemctl', '--user', 'is-active', unit],
                           capture_output=True, text=True, timeout=10)
        if r.stdout.strip() != 'active':
            bad.append('%s=%s' % (unit, r.stdout.strip()))
    assert not bad, ', '.join(bad)
    return '两个服务 active'


def env_health():
    r = subprocess.run([sys.executable, 'wsl/health.py'], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=60,
                       # 不给 DISPLAY：health.py 自己按配置挑屏（环境里的 :0 是 WSLg 的坑）
                       env=dict(os.environ))
    h = json.loads(r.stdout.strip().splitlines()[-1])
    assert h.get('ok'), 'health ok=false: %s' % {k: h.get(k) for k in
                                                 ('state', 'wechat', 'stop_file', 'observed_chats')}
    return 'ok · %s · 会话 %s · 客户端 %sMB' % (h.get('state'), h.get('chats_observed'),
                                              h.get('wechat_rss_mb'))


# ---------- 2. 朋友圈发布四道闸门（dry_run，不碰 UI） ----------
def moment_gates():
    """在临时目录里自造草稿验四道闸门——不依赖现在有没有待审草稿，随时可跑。"""
    import tempfile
    from moment_release import MomentRelease
    cfg = json.loads((ROOT / 'config' / 'resident.json').read_text())['moments']
    coords = json.loads((ROOT / 'config' / 'moments-coords.json').read_text())
    tmp = Path(tempfile.mkdtemp())
    img = tmp / 'pic.png'
    img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 64)

    def fresh():
        db = sqlite3.connect(':memory:')
        # 表结构跟 MomentComposer 保持一致（这里不实例化 composer，避免真调用模型）
        db.execute('CREATE TABLE IF NOT EXISTS moments(id INTEGER PRIMARY KEY, created REAL,'
                   ' topic TEXT, seed TEXT, text TEXT, image TEXT, state TEXT, published REAL)')
        db.execute('CREATE TABLE IF NOT EXISTS moment_meta(key TEXT PRIMARY KEY, value TEXT)')
        rel = MomentRelease(db, None, composer=None, coords=coords,
                            state_dir=tmp, cfg=dict(cfg, with_image=True))
        db.execute('INSERT INTO moments(created,topic,seed,text,image,state)'
                   " VALUES(?,?,?,?,?,'DRAFT')",
                   (time.time(), 'daily', 'seed', '今天拍了张云，像棉花糖', str(img)))
        db.commit()
        return rel, db.execute('SELECT max(id) FROM moments').fetchone()[0]

    # 没令牌 → 拒
    rel0, mid0 = fresh()
    try:
        rel0._publish(mid0, dry_run=True)
        raise AssertionError('没令牌竟然放行')
    except Exception as exc:
        assert '批准令牌' in str(exc), str(exc)
    # 有令牌 → 四道闸门全过
    rel, mid = fresh()
    rel.approve(mid)
    res = rel._publish(mid, dry_run=True)
    assert res.get('approved') and res.get('dry_run')
    # 改一个字 → 令牌失效
    rel.db.execute("UPDATE moments SET text=text||'！' WHERE id=?", (mid,))
    rel.db.commit()
    try:
        rel._publish(mid, dry_run=True)
        raise AssertionError('改过内容令牌竟然还有效')
    except Exception as exc:
        assert '批准令牌' in str(exc), str(exc)
    # 有发布占位 → 一律拒（禁止重发）
    rel2, mid2 = fresh()
    rel2.approve(mid2)
    (tmp / 'PUBLISH_ATTEMPT').write_text('{}')
    try:
        rel2._publish(mid2, dry_run=True)
        raise AssertionError('有 PUBLISH_ATTEMPT 竟然放行')
    except Exception as exc:
        assert '禁止重发' in str(exc) or '发布尝试' in str(exc), str(exc)
    (tmp / 'PUBLISH_ATTEMPT').unlink()
    return '无令牌/改内容/有发布占位 三种都被拒；正常令牌放行'


def moment_draft_pending():
    """现在有没有草稿在等人审——这是信息，不是通过/失败。"""
    db = sqlite3.connect(str(STATE / 'ledger.sqlite'))
    row = db.execute("SELECT id, substr(text,1,24) FROM moments WHERE state='DRAFT'").fetchone()
    if not row:
        raise SkipCheck('当前没有待审草稿（post 发出去之后就会这样）')
    return 'id=%s 待审：%s…' % (row[0], row[1])


# ---------- 3. 互动管道安全闸 ----------
def interact_gates():
    from moment_interact import MomentInbox, InteractionPipeline, InteractGuard

    class FakeModel:
        def __init__(self, decisions, comments):
            self.decisions, self.comments, self.calls = decisions, comments, []
        def call(self, messages, max_tokens=900):
            sysmsg = str(messages[0].get('content', '')) if messages else ''
            self.calls.append('decide' if '决策' in sysmsg else 'compose')
            return json.dumps(self.decisions if '决策' in sysmsg else self.comments,
                              ensure_ascii=False)

    def inbox():
        return MomentInbox(sqlite3.connect(':memory:'))

    cfg = {'whitelist_only': True, 'friends': [], 'comment_max': 60}
    i1 = inbox(); i1.add('很帅的年糕', '今天拍了张云', False, 'a')
    m1 = FakeModel([{'id': 1, 'interact': True, 'reason': 'x'}], [])
    s1 = InteractionPipeline(m1, cfg).run_batch(i1)
    assert s1.get('skipped') == 'whitelist_only_no_friends' and not m1.calls, s1

    cfg2 = dict(cfg, friends=['很帅的年糕'])
    i2 = inbox(); i2.add('很帅的年糕', '今天拍了张云', False, 'b')
    m2 = FakeModel([{'id': 1, 'interact': True, 'reason': 'x'}],
                   [{'id': 1, 'comment': '加我微信 13800000000'}])
    s2 = InteractionPipeline(m2, cfg2).run_batch(i2)
    assert s2.get('commented') == 0, '含手机号的评论必须拦下: %s' % s2

    g = InteractGuard({'max_per_day': 3, 'min_interval_seconds': 600})
    i3 = inbox()
    for k in range(1, 6):
        i3.add('很帅的年糕', '第%d条' % k, False, 'c%d' % k)
    ok, _ = g.check(i3, now=1000000)
    assert ok, '干净状态应该放行'
    i3.mark_done(1, when=999900)
    ok2, why2 = g.check(i3, now=1000000)
    assert not ok2 and 'interval' in why2, why2
    for k, t in ((2, 996000), (3, 997000), (4, 998000)):
        i3.mark_done(k, when=t)
    ok3, why3 = g.check(i3, now=1000000)
    assert not ok3 and 'day' in why3, why3
    return '白名单 fail-closed / 隐私拦下 / 频率两道闸都拦'


# ---------- 4. 朋友圈草稿：节奏 + 选题 + 安全闸 ----------
def moment_draft_gates():
    from moments import MomentComposer
    from moments_safe import TOPIC_WHITELIST

    class DraftModel:
        def __init__(self, texts):
            self.texts, self.calls = list(texts), 0
        def call(self, messages, max_tokens=900):
            self.calls += 1
            return self.texts.pop(0) if self.texts else '入秋的风开始有形状了'

    def composer(texts, cfg=None):
        return MomentComposer(sqlite3.connect(':memory:'), DraftModel(texts),
                              cfg or {'min_days': 2, 'max_days': 3, 'max_chars': 300,
                                      'with_image': True})

    c1 = composer([])
    c1.due()          # 第一次看 due 才会生成随机间隔天数
    iv = float(c1._meta('interval_days'))
    assert 2 <= iv <= 3, '间隔应在 2-3 天: %s' % iv
    d1 = c1.draft()
    c1.mark_published(d1['id'])
    assert not c1.due(), '刚发过不该 due'
    c1._set_meta('last_published', time.time() - 4 * 86400)
    assert c1.due(), '4 天后该 due'
    topics = {c1.next_seed()[0] for _ in range(30)}
    assert topics <= set(TOPIC_WHITELIST), '选题越界: %s' % (topics - set(TOPIC_WHITELIST))
    c2 = composer(['今天股市涨停了三支，推荐买入', '云像棉花糖'])
    d2 = c2.draft()
    assert d2['text'] == '云像棉花糖', '不安全那条不能落库'
    c3 = composer(['股票涨停'] * 5)
    assert c3.draft() is None, '连续不安全必须放弃'
    return '节奏 %.2f 天 / 选题白名单 / 不安全文案不落库' % iv


# ---------- 5. 隐私判据统一 ----------
def privacy_uniform():
    from moments_safe import sanitize_for_moment
    from output_safe import check_output, OutputSafetyError
    bad = '加我微信 13800000000'
    for fn, name in ((lambda t: sanitize_for_moment(t, 200), '朋友圈'),
                     (lambda t: check_output(t, 200), '私聊输出')):
        try:
            fn(bad)
            raise AssertionError('%s 这条路没拦住手机号' % name)
        except (ValueError, OutputSafetyError):
            pass
    return '朋友圈与私聊输出同一套隐私判据'


# ---------- 6. 单元测试 ----------
def unit_tests():
    r = subprocess.run([sys.executable, 'wsl/time-tests.py'], cwd=str(ROOT),
                       capture_output=True, text=True, timeout=900)
    # unittest 的结果写 stderr（不是 stdout），两块都要看
    combined = (r.stdout or '') + (r.stderr or '')
    tail = [ln for ln in combined.splitlines()
            if ln.startswith(('Ran ', 'OK', 'FAILED')) or 'External I/O' in ln]
    assert r.returncode == 0 and 'OK' in combined, ' · '.join(tail[-4:])
    return ' · '.join(tail[-3:])


def main():
    check('环境：两个 systemd 服务', env_services)
    check('环境：健康 JSON', env_health)
    check('朋友圈：发布四道闸门（自造草稿）', moment_gates)
    check('朋友圈：当前待审草稿', moment_draft_pending)
    check('互动：白名单/隐私/频率', interact_gates)
    check('朋友圈：草稿节奏/选题/安全闸', moment_draft_gates)
    check('安全：隐私判据统一', privacy_uniform)
    if '--tests' in sys.argv:
        check('离线单元测试', unit_tests)

    width = max(len(n) for _, n, _ in RESULTS)
    print('=' * (width + 40))
    for ok, name, detail in RESULTS:
        mark = '✅' if ok else ('⏭️' if ok is None else '❌')
        print('%s  %-*s  %s' % (mark, width, name, detail))
    print('=' * (width + 40))
    bad = [n for ok, n, _ in RESULTS if ok is False]
    skipped = [n for ok, n, _ in RESULTS if ok is None]
    tail = ''
    if bad:
        tail = '：' + ', '.join(bad)
    elif skipped:
        tail = '（%d 项不适用）' % len(skipped)
    else:
        tail = '（全部通过）'
    print('总计 %d 项，失败 %d 项%s' % (len(RESULTS), len(bad), tail))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
