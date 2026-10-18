"""带图行为测试：每 3 条补一张、关键词必发、生图在后台、发送不堵队列。

生图走真 API 一次 20 秒还要花钱，所以这里把 generate_image 整个 mock 掉，
并把 threading.Thread 换成同步执行——这样才能断言"队列完 → 图已生成 → 待发送"。
"""
import hashlib, sqlite3, sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).parent/'src'))
sys.path.insert(0, str(Path(__file__).parent))

import resident as resident_mod
from resident import Resident
from test_integration import FakeWeChatUI, FakeNavigator, FakeConfig

GROUP = '测试群'
CK = 'group:' + GROUP


class SyncThread:
    """把后台线程换成同步执行：测试里才能确定性地断言中间状态。"""

    def __init__(self, target=None, args=(), daemon=None):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


def make_resident(cfg):
    from quota import Quota
    r = Resident.__new__(Resident)
    r.db = sqlite3.connect(':memory:')
    r.db.execute('CREATE TABLE deliveries(id INTEGER PRIMARY KEY, created REAL,'
                 ' state TEXT, digest TEXT)')
    r.quota = Quota(r.db)          # status() 会读额度状态，得给它一个真的
    r.image_sent = {}
    r.events = []
    r.stop = Path('definitely-not-a-stop-file')
    return r

FAKE_PNG = b'\x89PNG-fake-bytes'


class SamplingTests(unittest.TestCase):
    def setUp(self):
        self.r = make_resident(CFG)
        self.conf = dict(resident_mod.Resident.IMAGE_REPLY_DEFAULTS,
                         every_n=3, max_per_hour=99)

    def msg(self, text='随便聊聊'):
        return [{'direction': 'in', 'kind': 'text', 'text': text}]

    def test_every_third_reply_attaches(self):
        got = [self.r.should_attach_image(CK, self.conf, self.msg())[0] for _ in range(6)]
        self.assertEqual(got, [False, False, True, False, False, True])

    def test_explicit_ask_always_wins(self):
        for i in range(5):
            want, why = self.r.should_attach_image(CK, self.conf, self.msg('发个图看看'))
            self.assertTrue(want)
            self.assertEqual(why, 'asked')

    def test_every_n_zero_disables_sampling(self):
        conf = dict(self.conf, every_n=0)
        got = [self.r.should_attach_image(CK, conf, self.msg())[0] for _ in range(6)]
        self.assertEqual(set(got), {False})

    def test_counters_are_per_chat(self):
        """每个群各自数自己的条数：A 群到第 3 条不会把 B 群的第 1 条也带图。"""
        other = 'group:别的群'
        seq = [(CK, False), (CK, False), (CK, True),
               (other, False), (other, False), (other, True)]
        for ck, want in seq:
            got, _ = self.r.should_attach_image(ck, self.conf, self.msg())
            self.assertEqual(got, want)


class AsyncImageTests(unittest.TestCase):
    def setUp(self):
        self.r = make_resident(CFG)
        self.ui = FakeWeChatUI()
        self.r.nav = FakeNavigator(self.ui)
        self.statuses = []
        st = mock.patch.object(resident_mod, 'atomic_json',
                               lambda path, value: self.statuses.append(value))
        st.start()
        self.addCleanup(st.stop)
        thr = mock.patch.object(resident_mod.threading, 'Thread', SyncThread)
        thr.start()
        self.addCleanup(thr.stop)
        import tempfile as _tempfile
        fake_png_path = _tempfile.gettempdir() + '/fake-oc-image.png'
        open(fake_png_path, 'wb').write(FAKE_PNG)
        gen = mock.patch.object(resident_mod, 'generate_image',
                                return_value=fake_png_path)
        gen.start()
        self.addCleanup(gen.stop)
        png = mock.patch.object(resident_mod, 'prepare_png_bytes',
                                return_value=(FAKE_PNG, 100, 100))
        png.start()
        self.addCleanup(png.stop)
        oc = mock.patch.object(resident_mod, 'OC_REF', None)
        oc.start()
        self.addCleanup(oc.stop)
        cfgp = mock.patch.object(resident_mod, 'CONFIG', FakeConfig(CFG))
        cfgp.start()
        self.addCleanup(cfgp.stop)

    def conf(self, **kw):
        base = dict(resident_mod.Resident.IMAGE_REPLY_DEFAULTS)
        base.update(every_n=3, max_per_hour=99)
        base.update(kw)
        return base

    def prime(self):
        """预置计数=2：下一条就是第 3 条，会触发抽样补图。"""
        self.r.image_counter = {CK: 2}

    def test_generation_runs_in_background_and_stays_pending(self):
        self.prime()
        with mock.patch.object(resident_mod, 'ChatNavigator', FakeNavigator):
            sent = self.r.maybe_send_image_reply(CFG, self.ui, GROUP, CK,
                                                 [{'text': '聊聊'}])
        self.assertTrue(sent)
        job = self.r._image_jobs()[0]
        self.assertEqual(job['state'], 'ready')            # 同步线程跑完了
        self.assertEqual(job['why'], 'sampled')            # 第 3 条触发

    def test_flush_sends_with_expected_chat(self):
        self.prime()
        with mock.patch.object(resident_mod, 'ChatNavigator', FakeNavigator):
            self.r.maybe_send_image_reply(CFG, self.ui, GROUP, CK, [{'text': '聊聊'}])
        sent = []
        with mock.patch.object(FakeWeChatUI, 'send_image_png', create=True,
                               side_effect=lambda png, expected_chat=None, **kw:
                               sent.append((expected_chat, png))):
            n = self.r.flush_pending_images(CFG, self.ui)
        self.assertEqual(n, 1)
        self.assertEqual(sent[0][0], GROUP)
        self.assertEqual(self.r._image_jobs()[0]['state'], 'sent')
        row = self.r.db.execute('SELECT state FROM deliveries').fetchone()
        self.assertEqual(row[0], 'IMAGE_SUBMITTED')

    def test_flush_never_crashes_on_failure(self):
        self.prime()
        with mock.patch.object(resident_mod, 'ChatNavigator', FakeNavigator):
            self.r.maybe_send_image_reply(CFG, self.ui, GROUP, CK, [{'text': '聊聊'}])

        def boom(self_, png, expected_chat=None, **kw):
            raise RuntimeError('粘贴失败')
        with mock.patch.object(FakeWeChatUI, 'send_image_png', create=True, side_effect=boom):
            n = self.r.flush_pending_images(CFG, self.ui)
        self.assertEqual(n, 0)
        self.assertEqual(self.r._image_jobs()[0]['state'], 'failed')

    def test_generate_failure_marks_job_failed(self):
        def boom(prompt, ref_image=None):
            raise RuntimeError('生图服务挂了')
        job = {'ck': CK, 'chat': GROUP, 'prompt': 'p', 'state': 'generating'}
        with mock.patch.object(resident_mod, 'generate_image', side_effect=boom):
            self.r._generate_image_job(job)
        self.assertEqual(job['state'], 'failed')

    def test_rate_limit_blocks_extra_images(self):
        """每 3 条触发一次，但每小时上限 1 张：第 1 张之后全被拦下。"""
        cfg = {**CFG, 'image_reply': {'enabled': True, 'every_n': 3, 'max_per_hour': 1}}
        for i in range(6):
            self.r.maybe_send_image_reply(cfg, self.ui, GROUP, CK,
                                          [{'text': '第%d条' % i}])
        self.assertEqual(len(self.r._image_jobs()), 1)
        self.assertEqual(self.r._image_jobs()[0]['state'], 'ready')

    def test_reply_image_scaled_to_sticker_size(self):
        """2026-10-18 用户：回复配图"当表情包用，小一点没关系"——最长边按 max_px 缩。"""
        cfg = {**CFG, 'image_reply': {'enabled': True, 'every_n': 3,
                                      'max_per_hour': 99, 'max_px': 512}}
        self.prime()
        seen = []

        def fake_prepare(data, max_px=2048):
            seen.append(max_px)
            return (b'png', max_px, max_px)

        with mock.patch.object(resident_mod, 'ChatNavigator', FakeNavigator), \
             mock.patch.object(resident_mod, 'prepare_png_bytes', side_effect=fake_prepare):
            self.r.maybe_send_image_reply(cfg, self.ui, GROUP, CK, [{'text': '聊聊'}])
        self.assertEqual(seen, [512])
        self.assertEqual(self.r._image_jobs()[0]['width'], 512)

    def test_unset_max_px_keeps_full_resolution(self):
        """配置没写 max_px 时按 2048 走：朋友圈等要细节的路径不受影响。"""
        self.prime()
        seen = []

        def fake_prepare(data, max_px=2048):
            seen.append(max_px)
            return (b'png', max_px, max_px)

        with mock.patch.object(resident_mod, 'ChatNavigator', FakeNavigator), \
             mock.patch.object(resident_mod, 'prepare_png_bytes', side_effect=fake_prepare):
            self.r.maybe_send_image_reply(CFG, self.ui, GROUP, CK, [{'text': '聊聊'}])
        self.assertEqual(seen, [2048])

    def test_disabled_means_nothing_happens(self):
        cfg = {**CFG, 'image_reply': {'enabled': False, 'every_n': 3}}
        self.prime()
        sent = self.r.maybe_send_image_reply(cfg, self.ui, GROUP, CK, [{'text': '聊聊'}])
        self.assertFalse(sent)
        self.assertEqual(self.r._image_jobs(), [])


CFG = {
    'target_chat': '很帅的年糕', 'watch_chats': [GROUP], 'group_whitelist': [GROUP],
    'automation': {'enabled': True}, 'direct_enabled': True,
    'links': {'enabled': False}, 'image_reply': {'enabled': True, 'every_n': 3,
                                                 'max_per_hour': 99},
}


class StickerSizeTests(unittest.TestCase):
    """prepare_png_bytes 的尺寸上限：表情包 512、默认 2048、乱配置不缩成马赛克。"""

    def _png(self, size):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', size, (200, 120, 60)).save(buf, 'PNG')
        return buf.getvalue()

    def test_max_px_shrinks_longest_edge_and_keeps_ratio(self):
        from wechat_ui import prepare_png_bytes
        _png, w, h = prepare_png_bytes(self._png((1600, 900)), max_px=512)
        self.assertEqual((w, h), (512, 288))

    def test_default_and_garbage_keep_2048(self):
        from wechat_ui import prepare_png_bytes
        _png, w, h = prepare_png_bytes(self._png((2400, 1200)))
        self.assertEqual((w, h), (2048, 1024))
        _png, w, h = prepare_png_bytes(self._png((2400, 1200)), max_px=0)
        self.assertEqual((w, h), (2048, 1024))


if __name__ == '__main__':
    unittest.main()


class ImagePromptTests(unittest.TestCase):
    '''配图提示词：用户 2026-10-18 要求「要有意义、不太一样，自拍照太无趣」。

    老写法是「以 OC 形象画一张图」，模型就交一张站立挥手的自拍照；
    现在改成话题优先（把群聊内容演成场景）+ 构图轮换，这几条把方向钉死。
    '''

    def resident(self):
        return Resident.__new__(Resident)

    def msg(self, text):
        return [{'direction': 'in', 'kind': 'text', 'text': text}]

    def test_prompt_leads_with_the_topic(self):
        '''话题必须出现在提示词里：图要跟着群聊内容走，不能凭空画。'''
        p = self.resident().image_prompt(self.msg('GPT要是快一点就好了'))
        self.assertIn('GPT要是快一点就好了', p)

    def test_prompt_bans_selfie_and_portrait(self):
        '''明确禁掉自拍照和单人肖像站姿——那就是用户嫌无聊的东西。'''
        p = self.resident().image_prompt(self.msg('哈哈'))
        self.assertIn('不要自拍照', p)
        self.assertIn('不要单人肖像站姿', p)

    def test_composition_rotates_between_calls(self):
        '''连续出图构图必须轮换：八种构图连出八张不该重复。'''
        r = self.resident()
        got = [r.image_prompt(self.msg('x')).split('构图：')[1][:4]
               for _ in range(len(resident_mod.Resident.IMAGE_VARIETY))]
        self.assertEqual(len(set(got)), len(got))

    def test_appearance_has_no_baked_in_pose(self):
        '''外观描述不能写死姿势/表情，否则每张图都是同一张自拍照。

        2026-10-18 之前 oc-character.md 里写着挥手 + 张嘴笑，
        实测当晚每张配图都是同一个姿势——这里连人设文件一起钉住。
        '''
        pre = resident_mod.oc_prefix()
        self.assertNotIn('挥手', pre)
        self.assertNotIn('张嘴笑', pre)
        # 身份元素必须还在：换了角色就不认得了
        for keep in ('年糕', '探险帽', '双肩背包', '探险靴'):
            self.assertIn(keep, pre)

    def test_variety_list_is_not_degenerate(self):
        '''构图清单至少得有三种，否则「轮换」是空话。'''
        self.assertGreaterEqual(len(resident_mod.Resident.IMAGE_VARIETY), 3)
