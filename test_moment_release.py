"""朋友圈"人审令牌 → 安全闸 → 坐标标定 → 发布 → 状态回写"链路回归。

覆盖：无令牌/令牌损坏/令牌与请求不符/草稿不安全/配图缺失/坐标未标定/
发布后界面无变化（不确定）——这几种情况都必须"不发"，且草稿保持 DRAFT。
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from moment_release import MomentRelease, ReleaseError, load_coords  # noqa: E402
from moments import MomentComposer  # noqa: E402
from moments_publisher import PublisherError  # noqa: E402

COORDS = {'moments_icon': (131, 247), 'camera_icon': (10, 10),
          'file_path_input': (40, 40), 'file_open_button': (50, 50),
          'text_input': (20, 20), 'publish_button': (30, 30)}
SAFE = '红糖糍粑煎到脆响的那一秒最治愈'


class FakeUI:
    """模拟微信 UI：search ^Moments$ 返回窗口 id；import -window 按序列返回图片。"""
    SEQ = [(237, 237, 237), (200, 200, 200), (150, 150, 150)]

    GREEN = (7, 193, 96)          # 微信绿：编辑页 Post 按钮
    POST_ABS = (330, 130)         # 窗口原点(300,100) + publish_button(30,30)

    def __init__(self, changing=False, moments_open=True, fail_post=False):
        self.wid = '0x1'
        self.commands = []
        self.changing = changing
        self.moments_open = moments_open
        self.fail_post = fail_post          # 点 Post 后弹红条（图片没发出去）
        self.post_error_text = ''
        self.shots = 0
        self.posted = False       # 点了 Post 且真的生效 → 编辑页退出
        self.last_move = None
        self.paste_done = False   # clipboard_write 之后画面才变（粘贴前/后必须不同）
        self.after_paste = 0
        self.last_color = self.SEQ[0]

    def _next_color(self):
        if not self.paste_done:
            return self.SEQ[0]
        self.after_paste += 1
        return self.SEQ[1] if self.after_paste == 1 else self.SEQ[2]

    def _editor_image(self, color, at=None):
        """编辑页截图：没发出去时 Post 按钮位置是微信绿（发表成功的判据）。"""
        import io
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (573, 573), color)
        if not self.posted:
            d = ImageDraw.Draw(img)
            d.rectangle([10, 20, 50, 40], fill=self.GREEN)
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        data = buf.getvalue()
        if at is not None:          # 整屏截图：把窗口内容贴到实时原点
            from PIL import ImageDraw as _Draw
            screen = Image.new('RGB', (1280, 800), (255, 255, 255))
            screen.paste(Image.open(io.BytesIO(data)), at)
            if self.fail_post:      # 失败红条：红圆图标（整屏才看得到）
                d = _Draw.Draw(screen)
                d.ellipse([at[0] + 200, at[1] + 340, at[0] + 230, at[1] + 370],
                          fill=(250, 81, 81))
                d.ellipse([at[0] + 200, at[1] + 400, at[0] + 230, at[1] + 430],
                          fill=(250, 81, 81))
            out = io.BytesIO()
            screen.save(out, 'PNG')
            return out.getvalue()
        return data

    def run(self, args, data=None, timeout=12):
        self.commands.append(args)
        if args[:2] == ['xdotool', 'search']:
            pattern = args[-1] if args else ''
            if 'Moments' in pattern and self.moments_open:
                return b'12345\n'
            if 'Open' in pattern:
                return b'999\n'
            return b''
        if args[:2] == ['xdotool', 'mousemove'] and '--window' not in args and len(args) >= 4:
            try:
                self.last_move = (int(args[2]), int(args[3]))
            except ValueError:
                pass
        if args[:2] == ['xdotool', 'click'] and '--window' not in args and self.changing:
            if self.last_move and abs(self.last_move[0] - self.POST_ABS[0]) <= 20 \
                    and abs(self.last_move[1] - self.POST_ABS[1]) <= 15:
                if self.fail_post:
                    self.post_error_text = 'Photos not sent.'   # 编辑页收起但没发出去
                else:
                    self.posted = True   # changing=False 时点 Post 不生效（模拟不确定）
        if args[:2] == ['import', '-window']:
            if args[2] == 'root':       # 整屏截图：复用上一帧窗口颜色
                return self._editor_image(self.last_color, at=(300, 100))
            self.shots += 1
            self.last_color = self._next_color()
            return self._editor_image(self.last_color)
        if args[:2] == ['xdotool', 'getwindowgeometry']:
            # 发布链路用 --shell 格式读实时原点（窗口可移动），互动链路用人类可读格式
            if '--shell' in args:
                return b'X=300\nY=100\nWIDTH=650\nHEIGHT=429\nSCREEN=0\n'
            return b'Position: 300,100 (screen: 0)\nGeometry: 650x429\n'
        return b''

    def capture(self):
        # 独立于 import 的 SEQ 计数（open_moments_panel 会用到）
        from PIL import Image
        return Image.new('RGB', (980, 710), (237, 237, 237))

    def clipboard_write(self, text):
        self.pasted_text = text
        self.paste_done = True

    def ocr(self, image, psm=6):
        if getattr(self, 'post_error_text', ''):
            return self.post_error_text          # 模拟"Photos not sent."红条
        return getattr(self, 'pasted_text', '') if self.paste_done else ''


class Base(unittest.TestCase):
    def setUp(self):
        for name in ('moment_release.time.sleep', 'moments_publisher.time.sleep'):
            p = patch(name)
            p.start()
            self.addCleanup(p.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        self.db = sqlite3.connect(':memory:')
        self.cfg = {'max_chars': 300}
        self.composer = MomentComposer(self.db, None, {'max_chars': 300, 'with_image': True})
        # 默认草稿带一张真实存在的配图（走完整"选图→Enter→粘贴"流程）
        img = Path(self.tmp.name) / 'gen.png'
        img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
        self._insert(SAFE, image=str(img))

    def _insert(self, text, state='DRAFT', image=''):
        cur = self.db.execute(
            'INSERT INTO moments(created,topic,seed,text,image,state) VALUES(?,?,?,?,?,?)',
            (1.0, 'food', 'seed-x', text, image, state))
        self.db.commit()
        return cur.lastrowid

    def _rel(self, ui=None, coords=None):
        return MomentRelease(self.db, ui or FakeUI(), composer=self.composer,
                             coords=COORDS if coords is None else coords,
                             state_dir=self.state, cfg=self.cfg)


class ApprovalTests(Base):
    def test_no_token_means_no_publish(self):
        rel = self._rel()
        self.assertIsNone(rel.approved_id())
        with self.assertRaises(ReleaseError):
            rel.publish()

    def test_garbage_token_ignored(self):
        (self.state).mkdir(parents=True, exist_ok=True)
        (self.state / 'APPROVE_MOMENT').write_text('not json at all')
        self.assertIsNone(self._rel().approved_id())

    def test_approve_writes_token_with_tight_perms(self):
        rel = self._rel()
        path = rel.approve(1)
        self.assertTrue(Path(path).exists())
        self.assertEqual(json.loads(Path(path).read_text())['id'], 1)
        self.assertEqual(Path(path).stat().st_mode & 0o777, 0o600)
        self.assertEqual(rel.approved_id(), 1)

    def test_approve_refuses_unsafe_draft(self):
        bad = self._insert('今天股市涨停了三支')
        with self.assertRaises(ReleaseError):
            self._rel().approve(bad)
        self.assertFalse((self.state / 'APPROVE_MOMENT').exists())

    def test_approve_refuses_non_draft(self):
        self._insert('海拉鲁的云真好看', state='PUBLISHED')
        with self.assertRaises(ReleaseError):
            self._rel().approve(2)

    def test_revoke_removes_token(self):
        rel = self._rel()
        rel.approve(1)
        self.assertTrue(rel.revoke())
        self.assertFalse(rel.revoke())
        self.assertIsNone(rel.approved_id())

    def test_token_for_published_draft_is_invalid(self):
        rel = self._rel()
        rel.approve(1)
        self.composer.mark_published(1)
        self.assertIsNone(rel.approved_id())


class PublishTests(Base):
    def test_dry_run_passes_gates_without_touching_ui(self):
        rel = self._rel()
        rel.approve(1)
        out = rel.publish(dry_run=True)
        self.assertTrue(out['dry_run'])
        self.assertEqual(out['text'], SAFE)
        self.assertEqual(out['id'], 1)
        self.assertEqual(rel.ui.commands, [])
        row = self.db.execute("SELECT state FROM moments WHERE id=1").fetchone()[0]
        self.assertEqual(row, 'DRAFT')

    def test_real_publish_marks_published_and_clears_token(self):
        ui = FakeUI(changing=True)
        rel = self._rel(ui=ui)
        rel.approve(1)
        out = rel.publish()
        self.assertEqual(out['id'], 1)
        self.assertAlmostEqual(out['published'], __import__('time').time(), delta=5)
        row = self.db.execute("SELECT state,published FROM moments WHERE id=1").fetchone()
        self.assertEqual(row[0], 'PUBLISHED')
        self.assertTrue(row[1])
        self.assertIsNone(rel.approved_id())
        self.assertFalse((self.state / 'APPROVE_MOMENT').exists())
        # 已批准的完整发布必须经过 Post，不得把仅编辑页就绪记成成功。
        # 只取绝对坐标移动（--window 的是文件对话框内的窗口相对坐标）
        moves = [c for c in ui.commands
                 if c[:2] == ['xdotool', 'mousemove'] and '--window' not in c]
        # 面板已开（FakeUI 默认 moments_open=True）→ 绝不重复点朋友圈图标：
        # 侧边栏图标是开关，重点一次会把已打开的面板关掉。
        self.assertNotIn(['131', '247'], [c[2:] for c in moves])
        self.assertEqual(moves[0][2:], ['310', '110'])          # 相机图标（原点300,100+相对）
        # 文件对话框的点击走 --window 直送（Qt 对话框吃 XSendEvent）
        dlg_clicks = [c for c in ui.commands
                      if c[:2] == ['xdotool', 'click'] and '--window' in c]
        self.assertEqual(len(dlg_clicks), 1)
        # 人审发布入口必须真的调用 publish_now 并点一次 Post。
        post_move = [c for c in moves if c[2:] == ['330', '130']]
        self.assertEqual(len(post_move), 1)
        # 用 Enter 确认文件对话框（不是点 Open）
        entered = [c for c in ui.commands if c[:2] == ['xdotool', 'key'] and 'Return' in c]
        self.assertEqual(len(entered), 1)

    def test_safe_text_changed_after_approval_requires_reapproval(self):
        rel = self._rel()
        rel.approve(1)
        self.db.execute("UPDATE moments SET text='红糖糍粑今天也好香' WHERE id=1")
        self.db.commit()
        self.assertIsNone(rel.approved_id())
        with self.assertRaises(ReleaseError):
            rel.publish()
        self.assertEqual(rel.ui.commands, [])

    def test_image_bytes_changed_at_same_path_invalidates_approval(self):
        rel = self._rel()
        rel.approve(1)
        Path(rel.draft(1)['image']).write_bytes(b'new-image-bytes')
        self.assertIsNone(rel.approved_id())
        with self.assertRaises(ReleaseError):
            rel.publish()
        self.assertEqual(rel.ui.commands, [])

    def test_old_id_only_token_invalid(self):
        rel = self._rel()
        rel.approve_path.write_text(json.dumps({'id': 1, 'approved_at': 1}))
        self.assertIsNone(rel.approved_id())

    def test_stop_blocks_before_ui(self):
        rel = self._rel()
        rel.approve(1)
        (self.state / 'STOP').touch()
        with self.assertRaisesRegex(ReleaseError, 'STOP'):
            rel.publish()
        self.assertEqual(rel.ui.commands, [])

    def test_revoke_during_composition_prevents_post(self):
        rel = self._rel(ui=FakeUI(changing=True))
        rel.approve(1)
        with patch('moments_publisher.MomentsPublisher.publish', side_effect=lambda *a: rel.revoke()):
            with self.assertRaises(ReleaseError):
                rel.publish()
        self.assertFalse(rel.attempt_path.exists())
        self.assertFalse(any(c[:2] == ['xdotool', 'click'] for c in rel.ui.commands))
        self.assertEqual(rel.draft(1)['state'], 'DRAFT')

    def test_no_composer_prevents_any_ui(self):
        rel = self._rel()
        rel.composer = None
        rel.approve(1)
        with self.assertRaisesRegex(ReleaseError, 'composer'):
            rel.publish()
        self.assertEqual(rel.ui.commands, [])

    def test_post_uncertainty_blocks_repeat_submission(self):
        rel = self._rel(ui=FakeUI(changing=False))
        rel.approve(1)
        with patch('moments_publisher.MomentsPublisher.publish'):
            with self.assertRaises(PublisherError):
                rel.publish()
        self.assertTrue(rel.attempt_path.exists())
        self.assertEqual(rel.draft(1)['state'], 'DRAFT')
        prior = list(rel.ui.commands)
        with self.assertRaisesRegex(ReleaseError, '禁止重发'):
            rel.publish()
        self.assertEqual(rel.ui.commands, prior)

    def test_post_error_toast_blocks_published(self):
        """图片没发出去（Photos not sent.）时绝不能记成 PUBLISHED —— 2026-10-16 真实事故。"""
        ui = FakeUI(changing=True, fail_post=True)
        rel = self._rel(ui=ui)
        rel.approve(1)
        with self.assertRaises(PublisherError):
            rel.publish()
        self.assertEqual(rel.draft(1)['state'], 'DRAFT')
        self.assertIsNotNone(rel.approved_id())        # 令牌保留，人工核对后可重发
        self.assertTrue(rel.attempt_path.exists())    # 尝试占位留存：不自动重试

    def test_compose_only_cannot_mark_published(self):
        rel = self._rel()
        rel.approve(1)
        with patch('moments_publisher.MomentsPublisher.publish_now'):
            with self.assertRaisesRegex(ReleaseError, '提交尝试'):
                rel.publish()
        self.assertEqual(rel.draft(1)['state'], 'DRAFT')

    def test_image_required_blocks_text_only_draft(self):
        mid = self._insert(SAFE)
        rel = self._rel()
        rel.cfg['with_image'] = True
        rel.approve(mid)
        with self.assertRaisesRegex(ReleaseError, '没有配图'):
            rel.publish()
        self.assertEqual(rel.ui.commands, [])

    def test_publish_without_panel_icon_refuses(self):
        coords = {k: v for k, v in COORDS.items() if k != 'moments_icon'}
        ui = FakeUI(changing=True)
        rel = self._rel(ui=ui, coords=coords)
        rel.approve(1)
        with self.assertRaises(NotImplementedError):
            rel.publish()
        self.assertEqual([c for c in ui.commands if c[0] == 'xdotool'], [])
        self.assertEqual(self.db.execute("SELECT state FROM moments WHERE id=1").fetchone()[0],
                         'DRAFT')
        self.assertEqual(rel.approved_id(), 1)

    def test_uncalibrated_coords_refuse_before_any_click(self):
        ui = FakeUI()
        rel = self._rel(ui=ui, coords={'camera_icon': (1, 1), 'text_input': (2, 2)})
        rel.approve(1)
        with self.assertRaises(NotImplementedError):
            rel.publish()
        self.assertEqual([c for c in ui.commands if c[0] == 'xdotool'], [])
        self.assertEqual(self.db.execute("SELECT state FROM moments WHERE id=1").fetchone()[0],
                         'DRAFT')
        self.assertEqual(rel.approved_id(), 1)  # 令牌保留，标定后可原样重试

    def test_id_mismatch_between_token_and_request(self):
        rel = self._rel()
        rel.approve(1)
        other = self._insert('今天的云很好看')
        with self.assertRaises(ReleaseError):
            rel.publish(other)

    def test_missing_image_file_refuses(self):
        mid = self._insert(SAFE, image='/tmp/does-not-exist-xyz.png')
        rel = self._rel()
        with self.assertRaises(ReleaseError):
            rel.approve(mid)

    def test_image_present_is_accepted(self):
        img = Path(self.tmp.name) / 'gen.png'
        img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
        mid = self._insert(SAFE, image=str(img))
        rel = self._rel()
        rel.approve(mid)
        out = rel.publish(dry_run=True)
        self.assertEqual(out['image'], str(img))

    def test_uncertain_publish_keeps_draft_and_token(self):
        ui = FakeUI(changing=False)   # 发表后界面无变化
        rel = self._rel(ui=ui)
        rel.approve(1)
        with self.assertRaises(PublisherError):
            rel.publish()
        self.assertEqual(self.db.execute("SELECT state FROM moments WHERE id=1").fetchone()[0],
                         'DRAFT')
        self.assertEqual(rel.approved_id(), 1)

    def test_publish_rechecks_safety_gate(self):
        # 批准后库被外部改成不安全内容 → 发布前必须再拦一次
        rel = self._rel()
        rel.approve(1)
        self.db.execute("UPDATE moments SET text='分享一个翻墙教程' WHERE id=1")
        self.db.commit()
        with self.assertRaises(ReleaseError):
            rel.publish()


class PanelTests(Base):
    def test_open_panel_requires_calibration(self):
        ui = FakeUI(moments_open=False)
        rel = self._rel(ui=ui, coords={})
        with self.assertRaises(NotImplementedError):
            rel.open_moments_panel()
        self.assertEqual(ui.commands, [])

    def test_open_panel_clicks_icon(self):
        ui = FakeUI(moments_open=False)
        rel = self._rel(ui=ui, coords=dict(COORDS, moments_icon=(131, 247)))
        searches = {'n': 0}
        orig = ui.run
        def run(args, data=None, timeout=12):
            if args[:2] == ['xdotool', 'search'] and 'Moments' in args[-1]:
                searches['n'] += 1
                if searches['n'] == 1:
                    return b''   # 首次：面板未开
                return b'12345\n'  # 点击图标后出现
            return orig(args, data, timeout)
        ui.run = run
        shot = rel.open_moments_panel()      # 返回点击后的主窗口截图（供调用方核验）
        self.assertEqual(shot.size, (980, 710))
        moves = [c for c in ui.commands if c[:3] == ['xdotool', 'mousemove', '131']]
        self.assertEqual(len(moves), 1)

    def test_open_panel_skips_icon_when_already_open(self):
        ui = FakeUI()
        rel = self._rel(ui=ui, coords=dict(COORDS, moments_icon=(131, 247)))
        shot = rel.open_moments_panel()       # 面板已开：只截图，不再点图标
        self.assertEqual(shot.size, (980, 710))
        self.assertEqual([c for c in ui.commands if c[:2] == ['xdotool', 'mousemove']], [])


class LoadCoordsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / 'moments-coords.json'

    def test_missing_file_means_uncalibrated(self):
        self.assertEqual(load_coords({}, self.file), {})

    def test_file_values_are_loaded(self):
        self.file.write_text(json.dumps({'camera_icon': [1, 2], 'publish_button': None}))
        self.assertEqual(load_coords({}, self.file), {'camera_icon': [1, 2]})

    def test_cfg_overrides_file(self):
        self.file.write_text(json.dumps({'camera_icon': [1, 2], 'text_input': [3, 4]}))
        out = load_coords({'moments_ui': {'camera_icon': [9, 9], 'publish_button': [5, 6]}},
                          self.file)
        self.assertEqual(out, {'camera_icon': [9, 9], 'text_input': [3, 4],
                              'publish_button': [5, 6]})

    def test_broken_file_is_ignored(self):
        self.file.write_text('{{{not json')
        self.assertEqual(load_coords({'moments_ui': {'camera_icon': [7, 7]}}, self.file),
                         {'camera_icon': [7, 7]})


if __name__ == '__main__':
    unittest.main(verbosity=2)
