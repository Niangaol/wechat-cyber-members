import sys, unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent/'src'))
from moments_publisher import MomentsPublisher, PublisherError

class FakeUI:
    """假微信：run 记录命令；对 xdotool search ^Moments$ / ^Open$ 返回假窗口 id，
    import -window 按预定义颜色序列返回图片（模拟各阶段界面变化）。"""
    # 截图颜色序列：1=粘贴前 2=粘贴后 3=点Post前 4=点Post后
    # 0=粘贴前，1=粘贴后第一帧（还没渲染出来），2=渲染完成
    SEQ = [(237, 237, 237), (200, 200, 200), (150, 150, 150)]
    def __init__(self, moments_open=True, dialog_open=True):
        self.wid = '0x1'
        self.commands = []
        self.shots = 0
        self.moments_open = moments_open
        self.dialog_open = dialog_open
        self.pasted = []
        self.paste_done = False
        self.after_paste = 0
        self.last_color = self.SEQ[0]

    def _next_color(self):
        """粘贴后第一帧还是旧画面、第二帧才渲染出来（粘贴渲染延迟）。"""
        if not self.paste_done:
            return self.SEQ[0]
        self.after_paste += 1
        return self.SEQ[1] if self.after_paste == 1 else self.SEQ[2]

    def _png(self, color, size=(573, 573), at=None):
        import io
        from PIL import Image
        img = Image.new('RGB', size, color)
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        data = buf.getvalue()
        if at is not None:                      # 整屏截图：把窗口内容贴到实时原点
            screen = Image.new('RGB', (1280, 800), (255, 255, 255))
            screen.paste(Image.open(io.BytesIO(data)), at)
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
            if 'Open' in pattern and self.dialog_open:
                return b'999\n'
            return b''
        if args[:2] == ['import', '-window']:
            if args[2] == 'root':       # 整屏截图：复用上一帧窗口颜色（可见性比对要一致）
                return self._png(self.last_color, at=(300, 100))
            self.shots += 1
            self.last_color = self._next_color()
            return self._png(self.last_color)
        if args[:2] == ['xdotool', 'getwindowgeometry']:
            if '--shell' in args:
                return b'X=300\nY=100\nWIDTH=573\nHEIGHT=573\nSCREEN=0\n'
            return b'Position: 300,100 (screen: 0)\nGeometry: 650x429\n'
        return b''
    def capture(self):
        """open_moments_panel 会调 capture() 取主窗口实时原点并验证登录/几何。"""
        import io
        from PIL import Image
        self.last_abs = (0, 0)
        return Image.open(io.BytesIO(self.run(['import', '-window', self.wid, 'png:-']))).convert('RGB')

    def clipboard_write(self, text):
        self.pasted.append(text)
        self.pasted_text = text
        self.paste_done = True

    def ocr(self, image, psm=6):
        """编辑页 OCR：粘贴完成后能读到刚写进去的文案。"""
        if getattr(self, 'paste_lost', False):
            return ''
        return getattr(self, 'pasted_text', '') if self.paste_done else ''

BASE_COORDS = ['moments_icon', 'camera_icon', 'file_path_input', 'file_open_button',
               'text_input', 'publish_button']

def mkcoords(keys):
    return {k: (100 + i * 10, 200 + i * 5) for i, k in enumerate(keys)}

class PublisherTests(unittest.TestCase):
    def setUp(self):
        sleeper = patch('moments_publisher.time.sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_uncalibrated_refuses(self):
        ui = FakeUI()
        pub = MomentsPublisher(ui)
        with self.assertRaises(NotImplementedError):
            pub.publish('测试')
        self.assertEqual([c for c in ui.commands if c[0] == 'xdotool'], [])
    def test_partial_calibration_refuses(self):
        ui = FakeUI()
        pub = MomentsPublisher(ui, {'camera_icon': (10, 10), 'text_input': (20, 20)})
        with self.assertRaises(NotImplementedError):
            pub.publish('测试', image_path='/tmp/x.png')
    def test_full_calibration_reaches_compose(self):
        """全标定：走完 开面板→相机→路径→Enter→粘贴，停在发表前。"""
        ui = FakeUI()
        pub = MomentsPublisher(ui, mkcoords(BASE_COORDS))
        shot = pub.publish('测试文案', image_path='/tmp/x.png')
        self.assertEqual(shot.size, (573, 573))
        self.assertEqual(ui.pasted, ['测试文案'])
        # 开了 Moments 窗口
        self.assertTrue(any('Moments' in str(c) for c in ui.commands))
        # 键入了完整路径
        typed = [c for c in ui.commands if c[:2] == ['xdotool', 'type']]
        self.assertEqual(len(typed), 1)
        self.assertIn('/tmp/x.png', typed[0])
        # 用 Enter 确认（不是点 Open）
        entered = [c for c in ui.commands if c[:2] == ['xdotool', 'key'] and 'Return' in c]
        self.assertEqual(len(entered), 1)
        # 没有点发表按钮
        xy = mkcoords(BASE_COORDS)['publish_button']
        self.assertFalse(any('mousemove' in c and str(xy[0]) in c and str(xy[1]) in c
                             for c in ui.commands))
    def test_publish_text_only_never_touches_camera(self):
        """纯文字动态绝不点相机图标、绝不弹文件框（否则文案会打进对话框）。"""
        ui = FakeUI()
        pub = MomentsPublisher(ui, mkcoords(BASE_COORDS))
        shot = pub.publish('测试文案', image_path=None)
        self.assertEqual(shot.size, (573, 573))
        cam = mkcoords(BASE_COORDS)['camera_icon']
        self.assertFalse(any(c[:2] == ['xdotool', 'mousemove']
                             and c[2:] == [str(300 + cam[0]), str(100 + cam[1])]
                             for c in ui.commands))
        # 不开文件框：不键入路径、不按回车确认、不点相机
        self.assertFalse(any(c[:2] == ['xdotool', 'type'] for c in ui.commands))
        self.assertFalse(any('Return' in c for c in ui.commands if c[:2] == ['xdotool', 'key']))

    def test_publish_unchanged_raises(self):
        """粘贴后编辑页读不到文案（粘贴没生效）→ PublisherError（不重试）。"""
        ui = FakeUI()
        ui.paste_lost = True                # 画面在变，但文案始终没进去
        pub = MomentsPublisher(ui, mkcoords(BASE_COORDS))
        with self.assertRaises(PublisherError):
            pub.publish('测试文案', image_path='/tmp/x.png')
    def test_publish_now_clicks_post(self):
        """publish_now 才会点 Post；界面变化即算成功。"""
        ui = FakeUI()
        pub = MomentsPublisher(ui, mkcoords(BASE_COORDS))
        shot = pub.publish_now('测试文案', image_path='/tmp/x.png')
        self.assertEqual(shot.size, (573, 573))
        xy = mkcoords(BASE_COORDS)['publish_button']
        self.assertTrue(any(c[:2] == ['xdotool', 'mousemove']
                            and c[2:] == [str(300 + xy[0]), str(100 + xy[1])]
                            for c in ui.commands))
    def test_no_moments_window_raises(self):
        """Moments 窗口打不开 → PublisherError，不瞎点后面的。"""
        ui = FakeUI(moments_open=False)
        pub = MomentsPublisher(ui, mkcoords(BASE_COORDS))
        with self.assertRaises(PublisherError):
            pub.publish('测试文案')
    def test_no_file_dialog_raises(self):
        """点了相机但文件对话框不出现 → PublisherError。"""
        ui = FakeUI(dialog_open=False)
        pub = MomentsPublisher(ui, mkcoords(BASE_COORDS))
        with self.assertRaises(PublisherError):
            pub.publish('测试文案', image_path='/tmp/x.png')
    def test_like_comment_needs_interact_coords(self):
        """没有 interact_ui 标定 → NotImplementedError，一个 xdotool 都不发。"""
        ui = FakeUI()
        pub = MomentsPublisher(ui, mkcoords(['moment_more', 'menu_like']))
        with self.assertRaises(NotImplementedError):
            pub.like_and_comment('很帅的年糕', '好可爱的年糕！')
        self.assertEqual([c for c in ui.commands if c[0] == 'xdotool'], [])

    def test_focus_moment_not_verified_refuses(self):
        """信息流里核验不到作者 → PublisherError，不点任何东西。"""
        ui = FakeUI()
        pub = MomentsPublisher(ui, {'interact_ui': {'comment_input': [250, 480],
                                                    'comment_send': [467, 501],
                                                    'menu_like_offset': [68, 17],
                                                    'menu_comment_offset': [205, 18]}})
        with self.assertRaises(PublisherError):
            pub.focus_moment('很帅的年糕', ocr=lambda im, psm: '另外的人')

if __name__ == '__main__':
    unittest.main(verbosity=2)
