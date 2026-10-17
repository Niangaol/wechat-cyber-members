"""互动（赞/评）链路测试：发布器定位/菜单/发送 + 频率闸 + CLI 闸门。

全部用假微信（FakeUI）：不碰真微信、不碰真键鼠。
真机标定坐标见 config/moments-coords.json 的 interact_ui（2026-10-16 实测）。
"""
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'wsl'))

from moments_publisher import MomentsPublisher, PublisherError  # noqa: E402
from moment_interact import MomentInbox, InteractGuard, InteractionPipeline  # noqa: E402

import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location(
    'interact_release', ROOT / 'wsl' / 'interact-release.py')
interact_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(interact_release)
sys.modules['interact_release'] = interact_release   # 让 patch 能按名字找到


def feed_image(with_button=True):
    """造一张 573x573 的假信息流截图；with_button 时带 ··· 按钮像素特征。"""
    from PIL import Image
    im = Image.new('RGB', (573, 573), (255, 255, 255))
    px = im.load()
    if with_button:
        # 按钮：515-546 x 500-530，247 灰底 + 两个蓝灰点
        for y in range(500, 531):
            for x in range(515, 547):
                px[x, y] = (247, 247, 247)
        for x, y in [(523, 510), (538, 510), (523, 520), (538, 520)]:
            px[x, y] = (105, 123, 160)
    return im


def png_bytes(im):
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return buf.getvalue()


SOURCE_TEXT = '这张照片里的年糕好可爱'


class FakeUI:
    """假微信：信息流(带按钮)→评论框空→评论框有字→发送后 四阶段截图。"""

    STAGES = ['feed', 'feed', 'feed', 'feed', 'box_empty', 'box_typed', 'box_sent']

    def __init__(self, author='很帅的年糕', menu_open=True, with_button=True):
        self.commands = []
        self.pasted = []
        self.author = author
        self.menu_open = menu_open
        self.with_button = with_button
        self.calls = 0
        self.moments_wid = '0xM'

    def run(self, args, data=None, timeout=12):
        self.commands.append(args)
        head = args[:2]
        if head == ['xdotool', 'search']:
            pattern = args[-1]
            if 'Moments' in pattern:
                return b'12345\n'
            if 'wechat' in pattern:
                return b'67890\n' if self.menu_open else b''
            return b''
        if head == ['xdotool', 'getwindowgeometry']:
            if any('67890' in str(a) for a in args):
                return b'X=589\nY=650\nWIDTH=274\nHEIGHT=38\nSCREEN=0\n'
            return b'X=353\nY=114\nWIDTH=573\nHEIGHT=573\nSCREEN=0\n'
        if head == ['import', '-window']:
            stage = self.STAGES[min(self.calls, len(self.STAGES) - 1)]
            self.calls += 1
            if stage == 'feed':
                return png_bytes(feed_image(self.with_button))
            color = {'box_empty': (255, 255, 255), 'box_typed': (240, 240, 240),
                     'box_sent': (200, 200, 200)}[stage]
            from PIL import Image
            return png_bytes(Image.new('RGB', (573, 573), color))
        return b''

    def clipboard_write(self, text):
        self.pasted.append(text)

    def ocr(self, image, psm=6):
        return self.author + '\n' + SOURCE_TEXT


INTERACT_COORDS = {
    'comment_input': [250, 480],
    'comment_send': [467, 501],
    'more_button_x': 530,
    'more_scan_x1': 515,
    'more_scan_x2': 547,
    'menu_like_offset': [68, 17],
    'menu_comment_offset': [205, 18],
    'menu_size': [274, 38],
}


def mkpub(ui, coords=None):
    return MomentsPublisher(ui, {'interact_ui': coords or INTERACT_COORDS})


class FindMoreButtonsTests(unittest.TestCase):
    def test_detects_button(self):
        im = feed_image(True)
        found = MomentsPublisher.find_more_buttons(im)
        self.assertEqual(len(found), 1)
        x, y = found[0]
        self.assertEqual(x, 531)   # (515+547)//2
        self.assertAlmostEqual(y, 515, delta=6)

    def test_no_button_no_hit(self):
        self.assertEqual(MomentsPublisher.find_more_buttons(feed_image(False)), [])


class FocusMomentTests(unittest.TestCase):
    def setUp(self):
        sleeper = patch('moments_publisher.time.sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_verified_author_returns_button(self):
        ui = FakeUI(author='很帅的年糕')
        pub = mkpub(ui)
        bx, by = pub.focus_moment('很帅的年糕', target_text=SOURCE_TEXT)
        self.assertEqual(bx, 531)
        self.assertTrue(400 < by < 560)

    def test_unverified_author_refuses(self):
        ui = FakeUI(author='另外的人')
        pub = mkpub(ui)
        with self.assertRaises(PublisherError):
            pub.focus_moment('很帅的年糕', max_cards=2, target_text=SOURCE_TEXT)

    def test_no_button_in_feed_refuses(self):
        ui = FakeUI(with_button=False)
        pub = mkpub(ui)
        with self.assertRaises(PublisherError):
            pub.focus_moment('很帅的年糕', max_cards=2, target_text=SOURCE_TEXT)

    def test_author_substring_no_longer_authorizes(self):
        for author in ('年糕', '很帅的年糕的小号'):
            with self.subTest(author=author):
                ui = FakeUI(author=author)
                with self.assertRaises(PublisherError):
                    mkpub(ui).focus_moment('很帅的年糕', target_text=SOURCE_TEXT, max_cards=1)
                self.assertFalse(any(c[:3] == ['xdotool', 'click', '1'] for c in ui.commands))

    def test_same_author_different_body_refuses(self):
        ui = FakeUI()
        with self.assertRaises(PublisherError):
            mkpub(ui).focus_moment('很帅的年糕', target_text='这张照片里的年糕在睡觉', max_cards=1)
        self.assertFalse(any(c[:3] == ['xdotool', 'click', '1'] for c in ui.commands))

    def test_body_prefix_not_full_match(self):
        ui = FakeUI()
        with self.assertRaises(PublisherError):
            mkpub(ui).focus_moment('很帅的年糕', target_text=SOURCE_TEXT[:8], max_cards=1)

    def test_missing_short_or_truncated_body_refuses_before_navigation(self):
        for text in (None, '', '你好', '这张照片里的年糕…', '[图片]'):
            with self.subTest(text=text):
                ui = FakeUI()
                with self.assertRaises(PublisherError):
                    mkpub(ui).focus_moment('很帅的年糕', target_text=text)
                self.assertEqual(ui.commands, [])

    def test_multiple_cards_refuse_ambiguous_crop(self):
        ui = FakeUI()
        pub = mkpub(ui)
        with patch.object(pub, 'find_more_buttons', return_value=[(531, 250), (531, 515)]):
            with self.assertRaisesRegex(PublisherError, '歧义'):
                pub.focus_moment('很帅的年糕', target_text=SOURCE_TEXT)
        self.assertFalse(any(c[:3] == ['xdotool', 'click', '1'] for c in ui.commands))

    def test_render_changes_after_verification_refuse(self):
        ui = FakeUI()
        pub = mkpub(ui)
        first = feed_image()
        changed = first.copy()
        changed.putpixel((100, 100), (0, 0, 0))
        with patch.object(pub, 'scroll_feed_to_top'), patch.object(pub, '_shot', side_effect=[first, changed]):
            with self.assertRaisesRegex(PublisherError, '发生变化'):
                pub.focus_moment('很帅的年糕', target_text=SOURCE_TEXT)
        self.assertFalse(any(c[:3] == ['xdotool', 'click', '1'] for c in ui.commands))

    def test_line_wrapping_does_not_change_identity(self):
        ui = FakeUI()
        with patch.object(ui, 'ocr', return_value='很帅的年糕\n' + SOURCE_TEXT[:6] + '\n' + SOURCE_TEXT[6:]):
            self.assertEqual(mkpub(ui).focus_moment('很帅的年糕', target_text=SOURCE_TEXT)[0], 531)

    def test_scroll_points_stay_inside_moments_window(self):
        ui = FakeUI(author='其他人')
        with self.assertRaises(PublisherError):
            mkpub(ui).focus_moment('很帅的年糕', target_text=SOURCE_TEXT, max_cards=1)
        moves = [c for c in ui.commands if c[:2] == ['xdotool', 'mousemove']]
        self.assertTrue(moves)
        for c in moves:
            self.assertTrue(353 + 20 <= int(c[2]) < 353 + 573 - 20)
            self.assertTrue(114 + 60 <= int(c[3]) < 114 + 573 - 20)
        self.assertTrue(any(c == ['xdotool', 'click', '4'] for c in ui.commands))
        self.assertTrue(any(c == ['xdotool', 'click', '5'] for c in ui.commands))

    def test_explicit_out_of_bounds_scroll_has_no_mouse_event(self):
        ui = FakeUI()
        with self.assertRaisesRegex(PublisherError, '越界'):
            mkpub(ui).scroll_feed_to_top(feed_cx=640)
        self.assertFalse(any(c[:2] in (['xdotool', 'mousemove'], ['xdotool', 'click']) for c in ui.commands))

    def test_scroll_uses_new_origin_each_time(self):
        ui = FakeUI()
        pub = mkpub(ui)
        with patch.object(pub, '_win_origin', side_effect=[(100, 100), (200, 250)]):
            pub._scroll_feed(feed_image(), 4)
            pub._scroll_feed(feed_image(), 5)
        moves = [c for c in ui.commands if c[:2] == ['xdotool', 'mousemove']]
        self.assertEqual(moves[0][2:], ['386', '529'])
        self.assertEqual(moves[1][2:], ['486', '679'])

    def test_tiny_window_refuses_scroll(self):
        from PIL import Image
        ui = FakeUI()
        with self.assertRaises(PublisherError):
            mkpub(ui)._scroll_feed(Image.new('RGB', (30, 30)), 4)
        self.assertEqual(ui.commands, [])

    def test_empty_author_refuses(self):
        pub = mkpub(FakeUI())
        with self.assertRaises(PublisherError):
            pub.focus_moment('')


class LikeAndCommentTests(unittest.TestCase):
    def setUp(self):
        sleeper = patch('moments_publisher.time.sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_full_flow_like_and_comment(self):
        ui = FakeUI()
        pub = mkpub(ui)
        r = pub.like_and_comment('很帅的年糕', '好可爱的年糕！', target_text=SOURCE_TEXT)
        self.assertEqual(r['author'], '很帅的年糕')
        self.assertTrue(r['liked'])
        self.assertTrue(r['sent'])
        self.assertEqual(ui.pasted, ['好可爱的年糕！'])
        # 点了 ···、Like、Comment、输入框、Send 共 5 次左键点击（不含滚轮）
        clicks = [c for c in ui.commands
                  if c[0] == 'xdotool' and len(c) > 2 and c[1] == 'click'
                  and c[2] == '1']
        self.assertEqual(len(clicks), 5)
        # Like 在菜单左半 (589+68, 650+17)，Comment 在右半 (589+205, 650+18)
        moves = [c for c in ui.commands if c[:2] == ['xdotool', 'mousemove']]
        self.assertTrue(any('657' in c and '667' in c for c in moves))
        self.assertTrue(any('794' in c and '668' in c for c in moves))

    def test_no_like_never_clicks_like(self):
        ui = FakeUI()
        pub = mkpub(ui)
        r = pub.like_and_comment('很帅的年糕', '只评论不点赞', like=False, target_text=SOURCE_TEXT)
        self.assertFalse(r['liked'])
        moves = [str(c) for c in ui.commands if c[:2] == ['xdotool', 'mousemove']]
        self.assertFalse(any('657' in m and '667' in m for m in moves))

    def test_no_comment_never_opens_box(self):
        ui = FakeUI()
        pub = mkpub(ui)
        r = pub.like_and_comment('很帅的年糕', '', like=True, comment=False, target_text=SOURCE_TEXT)
        self.assertTrue(r['liked'])
        self.assertEqual(ui.pasted, [])
        moves = [str(c) for c in ui.commands if c[:2] == ['xdotool', 'mousemove']]
        self.assertFalse(any('794' in m and '668' in m for m in moves))

    def test_unsafe_comment_refused_before_any_click(self):
        ui = FakeUI()
        pub = mkpub(ui)
        with self.assertRaises(ValueError):
            pub.like_and_comment('很帅的年糕', '这条政治新闻真好看', target_text=SOURCE_TEXT)
        self.assertEqual([c for c in ui.commands if c[0] == 'xdotool'], [])

    def test_missing_coords_refuse_before_any_click(self):
        ui = FakeUI()
        pub = mkpub(ui, {'menu_like_offset': [68, 17]})
        with self.assertRaises(NotImplementedError):
            pub.like_and_comment('很帅的年糕', '你好', target_text=SOURCE_TEXT)
        self.assertEqual([c for c in ui.commands if c[0] == 'xdotool'], [])

    def test_revocation_just_before_like_prevents_click(self):
        from wechat_ui import SafetyError
        ui = FakeUI()
        calls = []
        def check():
            calls.append(True)
            if len(calls) == 3:
                raise SafetyError('撤权')
        with self.assertRaises(SafetyError):
            mkpub(ui).like_and_comment('很帅的年糕', '你好', before_action=check, target_text=SOURCE_TEXT)
        clicks = [c for c in ui.commands if c[:2] == ['xdotool', 'click'] and c[-1] == '1']
        self.assertEqual(len(clicks), 1)  # 只打开了菜单，没有点赞

    def test_revocation_before_send_prevents_submit(self):
        from wechat_ui import SafetyError
        ui = FakeUI()
        calls = []
        def check():
            calls.append(True)
            if len(calls) == 6:
                raise SafetyError('暂停')
        with self.assertRaises(SafetyError):
            mkpub(ui).like_and_comment('很帅的年糕', '你好', before_action=check, target_text=SOURCE_TEXT)
        self.assertEqual(ui.pasted, ['你好'])
        clicks = [c for c in ui.commands if c[:2] == ['xdotool', 'click'] and c[-1] == '1']
        self.assertEqual(len(clicks), 4)  # 菜单、赞、评论、输入框，没有发送

    def test_menu_not_appearing_raises(self):
        ui = FakeUI(menu_open=False)
        pub = mkpub(ui)
        with self.assertRaises(PublisherError):
            pub.like_and_comment('很帅的年糕', '你好', target_text=SOURCE_TEXT)

    def test_paste_no_change_raises_without_send(self):
        """粘贴后输入框无变化 → PublisherError，且没有点 Send。"""
        ui = FakeUI()
        pub = mkpub(ui)
        # 让 box_typed 与 box_empty 同色（无变化）
        orig = ui.run

        def run(args, data=None, timeout=12):
            out = orig(args, data, timeout)
            return out
        with patch.object(FakeUI, 'STAGES', ['feed', 'feed', 'feed', 'feed',
                                             'box_empty', 'box_empty',
                                             'box_sent']):
            with self.assertRaises(PublisherError):
                pub.like_and_comment('很帅的年糕', '你好', target_text=SOURCE_TEXT)
        sends = [c for c in ui.commands if c[:2] == ['xdotool', 'mousemove']
                 and '820' in c]
        self.assertEqual(sends, [])


class InteractGuardTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.inbox = MomentInbox(self.db)

    def _done(self, when):
        self.inbox.add('作者', '内容', False, 'fp-%s' % when)
        mid = self.db.execute('SELECT max(id) FROM moment_inbox').fetchone()[0]
        self.inbox.mark_done(mid, when)

    def test_fresh_inbox_ok(self):
        ok, why = InteractGuard({'max_per_day': 2, 'min_interval_seconds': 60}).check(
            self.inbox)
        self.assertTrue(ok)
        self.assertEqual(why, '')

    def test_day_quota_blocks(self):
        now = 1000000.0
        for i in range(2):
            self._done(now - 100 + i)
        ok, why = InteractGuard({'max_per_day': 2}).check(self.inbox, now)
        self.assertFalse(ok)
        self.assertIn('interact_quota_day', why)

    def test_interval_blocks(self):
        now = 1000000.0
        self._done(now - 30)
        ok, why = InteractGuard({'min_interval_seconds': 600}).check(self.inbox, now)
        self.assertFalse(ok)
        self.assertIn('interact_quota_interval', why)

    def test_old_done_not_counted(self):
        now = 1000000.0
        for i in range(5):
            self._done(now - 90000 + i)   # 25 小时前
        ok, _ = InteractGuard({'max_per_day': 4, 'min_interval_seconds': 0}).check(
            self.inbox, now)
        self.assertTrue(ok)


class InteractCliTests(unittest.TestCase):
    """CLI 闸门：令牌/安全/频率/标定四道全过才 dry_run_ok / execute。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'config').mkdir()
        cfg = json.loads((ROOT / 'config' / 'resident.json').read_text())
        cfg['interact'] = {'enabled': True, 'whitelist_only': True,
                           'friends': ['很帅的年糕'], 'max_per_day': 4,
                           'min_interval_seconds': 600}
        cfg['moments_ui'] = {}  # 不继承实机坐标
        (root / 'config' / 'resident.json').write_text(json.dumps(cfg))
        self.addCleanup(self.tmp.cleanup)
        self.state = root / 'state'
        self.state.mkdir()
        self.db = sqlite3.connect(self.state / 'ledger.sqlite')
        self.inbox = MomentInbox(self.db)
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE moments(state TEXT, published REAL)')
        self.db.execute("INSERT INTO moments VALUES('PUBLISHED', 1)")
        self.db.commit()
        self.inbox.add('很帅的年糕', '动态内容', False, 'fp-1')
        self.inbox.set_comment(1, '好可爱的年糕！')
        self.p_root = patch('interact_release.ROOT', root)
        self.p_state = patch('interact_release.STATE', self.state)
        self.p_root.start()
        self.p_state.start()
        self.addCleanup(self.p_root.stop)
        self.addCleanup(self.p_state.stop)

    def _argv(self, *extra):
        return ['interact-release.py'] + list(extra)

    def _run(self, *extra):
        buf = io.StringIO()
        with patch.object(sys, 'argv', self._argv(*extra)):
            with patch('sys.stdout', buf):
                code = interact_release.main()
        lines = [json.loads(l) for l in buf.getvalue().splitlines() if l.strip()]
        return code, lines

    def test_list_shows_items_and_guard(self):
        code, lines = self._run('--list')
        self.assertEqual(code, 0)
        ev = lines[0]
        self.assertEqual(ev['event'], 'interact_list')
        self.assertEqual(len(ev['items']), 1)
        self.assertTrue(ev['guard_ok'])
        self.assertFalse(ev['coords_calibrated'])   # 临时 root 无 moments-coords.json

    def test_no_token_refuses(self):
        code, lines = self._run('--dry-run')
        self.assertEqual(code, 4)
        self.assertEqual(lines[0]['event'], 'refused')

    def test_dry_run_passes_all_gates(self):
        coords_path = self.state.parent / 'config' / 'moments-coords.json'
        coords_path.write_text(json.dumps({'interact_ui': {'menu': [10, 20]}}))
        code, _ = self._run('--approve', '1')
        self.assertEqual(code, 0)
        code, lines = self._run('--dry-run')
        self.assertEqual(code, 0)
        self.assertEqual(lines[0]['event'], 'dry_run_ok')
        self.assertEqual(lines[0]['author'], '很帅的年糕')
        self.assertTrue(lines[0]['like'])

    def test_execute_blocked_by_frequency_guard(self):
        self._run('--approve', '1')
        now = 1000000.0
        for i in range(4):
            self.inbox.add('作者', 'x', False, 'fp-done-%d' % i)
            mid = self.db.execute('SELECT max(id) FROM moment_inbox').fetchone()[0]
            self.inbox.mark_done(mid, now - 10)
        with patch('moment_interact.time.time', return_value=now):
            code, lines = self._run('--execute')
        self.assertEqual(code, 4)
        self.assertIn('频率闸', lines[0]['reason'])

    def test_execute_blocked_when_uncalibrated(self):
        self._run('--approve', '1')
        code, lines = self._run('--execute')
        self.assertEqual(code, 3)
        self.assertEqual(lines[0]['event'], 'not_calibrated')

    def test_revoke_removes_token(self):
        self._run('--approve', '1')
        code, lines = self._run('--revoke')
        self.assertEqual(code, 0)
        self.assertTrue(lines[0]['removed'])

    def _calibrate(self):
        path = self.state.parent / 'config' / 'moments-coords.json'
        path.write_text(json.dumps({'interact_ui': INTERACT_COORDS}))

    def _config(self, **updates):
        path = self.state.parent / 'config' / 'resident.json'
        cfg = json.loads(path.read_text())
        cfg['interact'].update(updates)
        path.write_text(json.dumps(cfg))

    def test_approved_payload_change_invalidates_token(self):
        for field in ('author', 'text', 'comment', 'fingerprint'):
            with self.subTest(field=field):
                self._run('--approve', '1')
                self.db.execute('UPDATE moment_inbox SET ' + field + '=? WHERE id=1', ('已变更',))
                self.db.commit()
                code, lines = self._run('--execute')
                self.assertEqual(code, 4)
                self.assertEqual(lines[0]['event'], 'refused')

    def test_legacy_unbound_token_rejected(self):
        interact_release.token_path().write_text(json.dumps({'id': 1}))
        self.assertIsNone(interact_release.approved_id(self.inbox))

    def test_action_change_refused(self):
        self._run('--approve', '1')
        code, lines = self._run('--execute', '--no-like')
        self.assertEqual(code, 6)
        self.assertIn('动作', lines[0]['reason'])

    def test_stop_refuses_before_ui(self):
        self._run('--approve', '1')
        (self.state / 'STOP').touch()
        code, lines = self._run('--execute')
        self.assertEqual(code, 6)
        self.assertIn('STOP', lines[0]['reason'])

    def test_whitelist_revocation_refuses(self):
        self._run('--approve', '1')
        for friends in ([], ['其他人'], '很帅的年糕'):
            with self.subTest(friends=friends):
                self._config(friends=friends)
                code, lines = self._run('--execute')
                self.assertEqual(code, 6)
                self.assertIn('白名单', lines[0]['reason'])

    def test_missing_publication_refuses(self):
        self._run('--approve', '1')
        self.db.execute('DROP TABLE moments')
        self.db.commit()
        code, lines = self._run('--dry-run')
        self.assertEqual(code, 6)
        self.assertIn('发布链路', lines[0]['reason'])

    def test_only_draft_not_publication(self):
        self._run('--approve', '1')
        self.db.execute("UPDATE moments SET state='DRAFT'")
        self.db.commit()
        code, _ = self._run('--execute')
        self.assertEqual(code, 6)

    def test_execute_success_records_and_consumes(self):
        self._calibrate()
        self._run('--approve', '1')
        with patch.object(interact_release, 'WeChatUI'), patch.object(
                interact_release.MomentsPublisher, 'like_and_comment',
                return_value={'author': '很帅的年糕', 'liked': True, 'sent': True}):
            code, lines = self._run('--execute')
        self.assertEqual(code, 0)
        self.assertEqual(lines[0]['event'], 'interacted')
        self.assertFalse(interact_release.token_path().exists())
        self.assertEqual(self.db.execute('SELECT state FROM moment_inbox WHERE id=1').fetchone()[0], 'DONE')

    def test_disk_revocation_during_ui_aborts(self):
        self._calibrate()
        self._run('--approve', '1')
        def execute(*args, **kw):
            self._config(enabled=False)
            kw['before_action']()
            self.fail('撤权后不能执行')
        with patch.object(interact_release, 'WeChatUI'), patch.object(
                interact_release.MomentsPublisher, 'like_and_comment', side_effect=execute):
            code, lines = self._run('--execute')
        self.assertEqual(code, 6)
        self.assertIn('关闭', lines[0]['reason'])
        self.assertEqual(self.db.execute('SELECT state FROM moment_inbox WHERE id=1').fetchone()[0], 'READY')

    def test_partial_failure_blocks_retry_and_reapproval(self):
        self._calibrate()
        self._run('--approve', '1')
        with patch.object(interact_release, 'WeChatUI'), patch.object(
                interact_release.MomentsPublisher, 'like_and_comment',
                side_effect=PublisherError('点赞可能成功，评论失败')) as send:
            code, lines = self._run('--execute')
            self.assertEqual(code, 5)
            self.assertIn('禁止原样重试', lines[0]['note'])
            self.assertEqual(self._run('--execute')[0], 4)
            self.assertEqual(self._run('--approve', '1')[0], 6)
            self.assertEqual(send.call_count, 1)
        self.assertEqual(self.db.execute('SELECT state FROM interaction_attempts').fetchone()[0], 'UNCERTAIN')

    def test_unhandled_failure_still_quarantines(self):
        self._calibrate()
        self._run('--approve', '1')
        with patch.object(interact_release, 'WeChatUI'), patch.object(
                interact_release.MomentsPublisher, 'like_and_comment',
                side_effect=RuntimeError('意外中断')):
            with self.assertRaises(RuntimeError):
                self._run('--execute')
        self.assertEqual(self.db.execute('SELECT state FROM interaction_attempts').fetchone()[0], 'UNCERTAIN')
        self.assertEqual(self._run('--execute')[0], 4)

    def test_started_claim_survives_reopen_and_blocks_retry(self):
        self._run('--approve', '1')
        key = interact_release.claim_attempt(self.inbox, 1, True, True)
        self.assertTrue(key)
        # 模拟进程在 UI 中被杀，没有 finally；另一个连接仍应看到 STARTED。
        other_db = sqlite3.connect(self.state / 'ledger.sqlite')
        self.addCleanup(other_db.close)
        other = interact_release.open_inbox(other_db)
        self.assertIsNone(interact_release.approved_id(other))
        with self.assertRaises(interact_release.SafetyError):
            interact_release.claim_attempt(other, 1, True, True)
        self.assertEqual(self._run('--list')[1][0]['blocked_attempts'][0]['state'], 'STARTED')

    def test_other_item_blocked_while_attempt_unresolved(self):
        self._run('--approve', '1')
        interact_release.claim_attempt(self.inbox, 1, True, True)
        self.inbox.add('很帅的年糕', '另一条动态', False, 'fp-2')
        self.inbox.set_comment(2, '好可爱！')
        self._run('--approve', '2')
        with patch.object(interact_release, 'WeChatUI') as ui:
            code, lines = self._run('--execute')
        self.assertEqual(code, 6)
        self.assertIn('人工核对', lines[0]['reason'])
        ui.assert_not_called()

    def test_database_index_excludes_two_active_claims(self):
        self._run('--approve', '1')
        interact_release.claim_attempt(self.inbox, 1, True, True)
        other_db = sqlite3.connect(self.state / 'ledger.sqlite')
        self.addCleanup(other_db.close)
        with self.assertRaises(sqlite3.IntegrityError):
            other_db.execute('INSERT INTO interaction_attempts VALUES(?,?,?,?,?)',
                             (2, 'other-fp', 'other-key', 'STARTED', 1))
        other_db.rollback()

    def test_success_attempt_cannot_replay_even_if_inbox_reset(self):
        self.test_execute_success_records_and_consumes()
        self.inbox.set_comment(1, '又变回待发送')
        self.assertEqual(self._run('--approve', '1')[0], 6)
        self.assertEqual(self.db.execute('SELECT state FROM interaction_attempts').fetchone()[0], 'DONE')

    def test_two_concurrent_claimers_have_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        self._run('--approve', '1')
        barrier = Barrier(2)
        def claim():
            db = sqlite3.connect(self.state / 'ledger.sqlite')
            try:
                inbox = interact_release.open_inbox(db)
                barrier.wait(timeout=5)
                try:
                    interact_release.claim_attempt(inbox, 1, True, True)
                    return 'claimed'
                except interact_release.SafetyError:
                    return 'refused'
            finally:
                db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim), pool.submit(claim)]
            self.assertCountEqual([f.result(timeout=10) for f in futures], ['claimed', 'refused'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM interaction_attempts').fetchone()[0], 1)

    def test_same_fingerprint_cannot_replay_under_new_id(self):
        self.test_execute_success_records_and_consumes()
        self.db.execute("UPDATE moment_inbox SET fingerprint='changed-old' WHERE id=1")
        self.db.commit()
        self.inbox.add('很帅的年糕', '重复动态', False, 'fp-1')
        self.inbox.set_comment(2, '好可爱！')
        self._run('--approve', '2')
        self._config(max_per_day=100, min_interval_seconds=0)
        with patch.object(interact_release, 'WeChatUI') as ui:
            code, lines = self._run('--execute')
        self.assertEqual(code, 6)
        self.assertIn('禁止重复执行', lines[0]['reason'])
        ui.assert_not_called()

    def test_ui_busy_does_not_create_interaction_attempt(self):
        from ui_lease import UILeaseBusy
        self._calibrate()
        self._run('--approve', '1')
        with patch.object(interact_release, 'ui_lease', side_effect=UILeaseBusy('busy')), patch.object(
                interact_release, 'WeChatUI') as ui:
            code, lines = self._run('--execute')
        self.assertEqual(code, 7)
        self.assertEqual(lines[0]['event'], 'ui_busy')
        ui.assert_not_called()
        self.assertEqual(self.db.execute('SELECT count(*) FROM interaction_attempts').fetchone()[0], 0)

    def test_active_owner_callback_still_checks_authorization(self):
        self._calibrate()
        self._run('--approve', '1')
        def execute(*args, **kw):
            self.assertEqual(kw['target_text'], '动态内容')
            self.assertEqual(self.db.execute('SELECT state FROM interaction_attempts').fetchone()[0], 'STARTED')
            kw['before_action']()
            return {'liked': True, 'sent': True}
        with patch.object(interact_release, 'WeChatUI'), patch.object(
                interact_release.MomentsPublisher, 'like_and_comment', side_effect=execute):
            self.assertEqual(self._run('--execute')[0], 0)
        self.assertEqual(self.db.execute('SELECT state FROM interaction_attempts').fetchone()[0], 'DONE')

    def test_both_no_like_and_no_comment_aborts(self):
        code, lines = self._run('--execute', '--no-like', '--no-comment')
        self.assertEqual(code, 2)
        self.assertEqual(lines[0]['event'], 'aborted')


if __name__ == '__main__':
    unittest.main(verbosity=2)
