"""resident 集成测试：mock 微信窗口+模型，验证主循环全接线。
覆盖：观察→分级入队→排队发送→防发错窗→学习触发→限额休息→等待恢复→朋友圈草稿。"""
import json, sqlite3, sys, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT/'src'))
import os
import resident as resident_mod
import multimodal as multimodal_mod
from multimodal import image_data
from resident import Resident, chat_key_of


class FakeWeChatUI:
    """假微信：tone 由外部 change() 切换（模拟新消息到达后画面稳定）；run 记录命令。"""
    def __init__(self):
        self.wid = '0x1'
        self.commands = []
        self.shot_count = 0
        self.sent_texts = []
        self.tone = 237
    def change(self):
        self.tone = 220 if self.tone == 237 else 237
    def capture(self):
        self.shot_count += 1
        return Image.new('RGB', (980, 710), (self.tone, self.tone, self.tone))
    def ocr(self, image, psm=6):
        return ''   # 标题/草稿检测都返回空
    def run(self, args, data=None, timeout=12):
        self.commands.append(args)
        return b''
    def clipboard_read(self):
        return ''
    def clipboard_write(self, text):
        self.sent_texts.append(text)
    def verify_target(self, image=None, expected_chat=None):
        return self.capture()
    def send_text(self, text, expected_guard=None, expected_chat=None):
        if expected_guard is not None: expected_guard()
        self.sent_texts.append(('SENT', text))
        return self.capture()
    def chat_image(self, image):
        return image.crop((273, 70, image.width-3, 560))


class BusyUI(FakeWeChatUI):
    """聊天区一直在轻微变化：模拟对面机器人连发消息/聊天里有动图。

    旧逻辑用 sha256 全等判断"画面稳定"，这种会话会永远停在 debouncing、
    发送前校验永远 CHANGED——整条会话哑掉（2026-10-17 实测事故）。
    """

    def capture(self):
        from PIL import ImageDraw
        img = super().capture()
        d = ImageDraw.Draw(img)
        x = 300 + (self.shot_count % 5) * 3
        d.rectangle([x, 300, x + 40, 340], fill=(120, 120, 120))
        return img


class FakeNavigator:
    def __init__(self, ui):
        self.ui = ui
        self.switches = []
    def switch_to(self, name, use_cache=True):
        self.switches.append(name)
        return self.ui.capture()


class FlakyNavigator(FakeNavigator):
    """第一次切换失败（一过性），之后正常——用来测"切不进去也得留住消息"。"""

    def __init__(self, ui):
        super().__init__(ui)
        self.failed = False

    def switch_to(self, name, use_cache=True):
        # 只对"要发消息的那个会话"第一次切换失败，避免被观察阶段的切换提前吃掉
        if name == '家庭群' and not self.failed:
            self.failed = True
            self.switches.append(name)
            from wechat_ui import SafetyError
            raise SafetyError('切换后标题未精确匹配 %s' % name)
        return super().switch_to(name, use_cache)


class FakeModel:
    def __init__(self, reply_text='好的呀'):
        self.reply_text = reply_text
        self.calls = []
    def key(self):
        return 'fake-key'
    def reply(self, new_messages, history, web_sources, chat_context=None, hot_items=None):
        self.calls.append('reply')
        return self.reply_text
    def call(self, messages, max_tokens=900):
        self.calls.append(max_tokens)
        system = str(messages[0].get('content', '')) if messages else ''
        if '分析师' in system:
            return '{"style":"软萌","facts":[]}'
        if '决策官' in system or '评论家' in system:
            return '[]'  # 空决策/评论（batch 里无选中项时安全）
        if '朋友圈动态' in system or '朋友圈' in system:
            return '今天的云很好看'
        content = messages[-1].get('content', '') if isinstance(messages[-1], dict) else ''
        if isinstance(content, str) and content.startswith('['):
            return content
        return self.reply_text


class FakeConfig:
    """假配置文件对象：让 process_queue 里读 CONFIG 返回测试 cfg。
    不能 patch json.loads——那会 patch 到共享的 json 模块，连带毁掉凭证解析。"""
    def __init__(self, cfg):
        self._text = json.dumps(cfg)
    def read_text(self):
        return self._text


def make_resident(cfg, ui=None, model=None):
    """装配一个用临时状态目录的 Resident。返回 (r, patched)。
    调用方必须在 patched 上下文里跑 cycle（status/key/capture 都依赖 STATE patch）。"""
    tmp = tempfile.mkdtemp()
    (Path(tmp)/'credentials.json').write_text('{"step_plan_api_key":"test-key"}')
    ctx = (patch.object(resident_mod, 'STATE', Path(tmp)), patch.object(multimodal_mod, 'STATE', Path(tmp)),
           patch('multimedia.STATE', Path(tmp)))
    for c in ctx:
        c.start()
    r = Resident.__new__(Resident)
    state = Path(tmp); state.mkdir(parents=True, exist_ok=True)
    r.db = sqlite3.connect(str(state/'ledger.sqlite'))
    r.db.execute('CREATE TABLE IF NOT EXISTS deliveries(id INTEGER PRIMARY KEY, created REAL, state TEXT, digest TEXT)')
    from quota import Quota
    from memory import ChatMemory
    from search import HotFeed
    from moment_interact import MomentInbox
    r.quota = Quota(r.db)
    r.memory = ChatMemory(r.db)
    r.feed = HotFeed(r.db)
    r.inbox = MomentInbox(r.db)
    r.baselines, r.last_hash, r.last_sent, r.last_remind = {}, {}, {}, {}
    r.last_frame = {}
    r.seen_signatures = {}
    r.chat_failures = {}
    r.history = {}
    r.running, r.failures = True, 0
    r.moments, r.interact, r.nav, r.release = None, None, None, None
    r.stop = state/'STOP'
    r._tmp = tmp
    r._ctx = ctx
    return r


def stop_patches(r):
    for c in getattr(r, '_ctx', ()):
        c.stop()


BASE_CFG = {
    'target_chat': '很帅的年糕', 'watch_chats': [], 'group_whitelist': [],
    'display': ':99', 'poll_seconds': 1, 'debounce_seconds': 0, 'reply_max_chars': 200,
    'min_reply_seconds': 0, 'max_replies_per_hour': 30,
    'expected_width': 980, 'expected_height': 710,
    'limits': {'window_5h': 5, 'window_1d': 100},
    'remind_cooldown': 300,
    'step_plan': {'base_url': 'https://api.stepfun.com/step_plan/v1', 'model': 'step-5-preview',
                  'api_key_env': 'STEP_PLAN_API_KEY_TEST_NOPE', 'credential_file': 'credentials.json',
                  'timeout': 5, 'reasoning_effort': 'low'},
    'automation': {'enabled': True},
    # 群普通消息策略：测试里默认"全接"（要验的是别的行为）；
    # 正式群的 selective 规则由 test_group_policy.py 单独验。
    'groups': {'测试群': {'plain_mode': 'all'}, '家庭群': {'plain_mode': 'all'},
               'G': {'plain_mode': 'all'}},
    'links': {'enabled': False},
    'moments': {'enabled': False},
    'interact': {'enabled': False},
    'privacy': {'history_turns': 12},
}


class IntegrationTests(unittest.TestCase):
    def test_observe_only_when_disabled(self):
        cfg = dict(BASE_CFG, automation={'enabled': False})
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui = FakeWeChatUI()
        try:
            with patch('resident.WeChatUI', return_value=ui):
                r.cycle(cfg)
            self.assertEqual(ui.commands, [])
            st = json.loads((Path(r._tmp)/'status.json').read_text())
            self.assertEqual(st['state'], 'observe_only')
        finally:
            stop_patches(r)

    def test_multi_chat_switch_and_queue(self):
        """开自动化+两个监控会话：轮询切换、新消息入队、发送。"""
        cfg = dict(BASE_CFG, watch_chats=['家庭群'], group_whitelist=['家庭群'])
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.nav = FakeNavigator(ui)
        try:
            msg_a = {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': False,
                     'bbox': [80, 100, 200, 140], 'signature': 'sig-a'}
            msg_b = {'direction': 'in', 'kind': 'text', 'text': '吃了吗', 'at_me': False,
                     'bbox': [80, 200, 200, 240], 'signature': 'sig-b'}
            # cycle 内部构造的 ui/model 也必须是 Fake（否则真 capture 炸、真 API 花钱）
            with patch('resident.WeChatUI', return_value=ui), \
                 patch('resident.StepPlan', return_value=model):
                # 第一轮：建立 baseline（每会话一条已有消息）
                with patch('resident.CONFIG', FakeConfig(cfg)), \
                     patch('visual_parse.extract_messages', return_value=[msg_a]):
                    r.cycle(cfg)
                self.assertEqual(r.nav.switches, ['很帅的年糕', '家庭群'])
                # 第二轮：画面变化+消息追加（基线+新消息）→ 应入队
                ui.change()
                with patch('resident.CONFIG', FakeConfig(cfg)), \
                     patch('visual_parse.extract_messages', return_value=[msg_a, msg_b]):
                    r.cycle(cfg)
                # 两个会话都应入队（cycle 内会顺带处理掉先入的那条）
                self.assertTrue(r.quota.depth() >= 1)
                # 继续跑到队列清空 + 发送留痕
                with patch('resident.CONFIG', FakeConfig(cfg)), \
                     patch('visual_parse.extract_messages', return_value=[msg_a, msg_b]):
                    for _ in range(4):
                        r.cycle(cfg)
            sent = [t for t in ui.sent_texts if isinstance(t, tuple)]
            self.assertTrue(len(sent) >= 1)
            delivered = r.db.execute('SELECT count(*) FROM deliveries').fetchone()[0]
            self.assertTrue(delivered >= 1)  # 发送有留痕
            self.assertIn('很帅的年糕', r.nav.switches)
        finally:
            stop_patches(r)

    def test_no_viewport_overlap_still_replies_to_unseen(self):
        """视口不重叠（重启/滚动）时，只要该会话"已见"还在，没见过的新消息仍要回。"""
        cfg = dict(BASE_CFG, watch_chats=['家庭群'], group_whitelist=['家庭群'])
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.nav = FakeNavigator(ui)
        ck = 'group:家庭群'
        r.baselines[ck] = ['sig-old']
        r.seen_signatures[ck] = dict.fromkeys(['sig-old'])   # 有序集合（dict）
        r.last_hash[ck] = 'stale-digest'      # 强制走"画面变了"的路径
        msg_new = {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': True,
                   'bbox': [80, 100, 200, 140], 'signature': 'sig-new'}
        with patch('resident.WeChatUI', return_value=ui), \
             patch('resident.StepPlan', return_value=model), \
             patch('resident.CONFIG', FakeConfig(cfg)), \
             patch('visual_parse.extract_messages', return_value=[msg_new]):
            for _ in range(3):
                r.cycle(cfg)
        sent = [t for t in ui.sent_texts if isinstance(t, tuple)]
        self.assertTrue(sent, '没见过的入站消息必须回，不能被重建基线吞掉')

    def test_hot_source_rotation_picks_stalest(self):
        """热榜轮转按"最久没刷"选源——不能用内存指针（服务一重启就归零）。"""
        cfg = dict(BASE_CFG, hot_refresh_seconds=1)
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        now = time.time()
        from search import ROUTES
        for src, _route, _name in ROUTES:          # 全部先标记"刚刷过"
            r.db.execute("INSERT OR REPLACE INTO hot_meta(source,fetched) VALUES(?,?)",
                         (src, now))
        r.db.execute("INSERT OR REPLACE INTO hot_meta(source,fetched) VALUES('bilibili_hot',?)",
                     (now - 9999,))                # 只让 bilibili 变最旧
        r.db.commit()
        called = []
        r.feed.refresh = lambda only_source=None, force=False: (called.append(only_source), 1)[1]
        r.hot_checked = 0
        r.hot_cycle(cfg)
        self.assertEqual(called, ['bilibili_hot'], '要挑最久没刷的那个源')

    def test_unsafe_reply_is_regenerated_once(self):
        """出话没过安全闸：再生成一次（模型偶尔踩线）；仍不过才放弃并记原因。"""
        cfg = dict(BASE_CFG, watch_chats=[], group_whitelist=['家庭群'],
                   max_unsafe_retries=1)
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui = FakeWeChatUI()

        class UnsafeOnce(FakeModel):
            def __init__(self):
                super().__init__()
                self.calls = []
            def reply(self, *a, **k):
                self.calls.append('reply')
                return '13800000000 你打这个电话' if len(self.calls) == 1 else '好的呀'

        model = UnsafeOnce()
        r.nav = FakeNavigator(ui)
        payload = json.dumps({'messages': [
            {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': True,
             'bbox': [80, 100, 200, 140], 'signature': 'sig-1'}], 'want_search': False})
        r.quota.enqueue('group:家庭群', 0, payload)
        r.last_frame['group:家庭群'] = ui.chat_image(ui.verify_target(ui.capture()))
        with patch('resident.WeChatUI', return_value=ui), \
             patch('resident.StepPlan', return_value=model), \
             patch('resident.CONFIG', FakeConfig(cfg)), \
             patch('visual_parse.extract_messages', return_value=[]):
            for _ in range(3):
                r.cycle(cfg)
        sent = [t[1] for t in ui.sent_texts if isinstance(t, tuple)]
        self.assertEqual(sent, ['好的呀'], '第二次生成要通过并发出')
        self.assertNotIn('13800000000', ' '.join(sent), '带隐私内容的回复绝不能发出去')
        self.assertEqual(len(model.calls), 2)
        rows = [x[0] for x in r.db.execute("SELECT state FROM queue ORDER BY id")]
        self.assertIn('UNSAFE_RETRY', rows)

    def test_reply_to_existing_is_a_real_switch(self):
        """automation.reply_to_existing 以前写在配置里没人读（配置撒谎）。

        现在：true = 首次看到某会话时连历史消息一起回一次；false（默认）= 只建基线不回放。
        """
        for flag, expect_queue in ((False, 0), (True, 1)):
            cfg = dict(BASE_CFG, watch_chats=['家庭群'], group_whitelist=['家庭群'],
                       automation={'enabled': True, 'reply_to_existing': flag})
            r = make_resident(cfg)
            self.addCleanup(stop_patches, r)
            self.addCleanup(r.db.close)
            ui, model = FakeWeChatUI(), FakeModel()
            r.nav = FakeNavigator(ui)
            msg = {'direction': 'in', 'kind': 'text', 'text': '在吗',
                   'at_me': True, 'bbox': [80, 100, 200, 140], 'signature': 'sig-x'}
            with patch('resident.CONFIG', FakeConfig(cfg)), \
                 patch('resident.StepPlan', return_value=model), \
                 patch('visual_parse.extract_messages', return_value=[msg]):
                r.observe_one(cfg, ui, model, '家庭群', ui.capture())
            self.assertEqual(r.quota.depth(), expect_queue,
                             'reply_to_existing=%s 时应入队 %d 条' % (flag, expect_queue))

    def test_ui_down_uses_long_backoff(self):
        """UI 不可用时退避：否则登录窗一晚能刷出几万行日志、空转几千轮。"""
        cfg = dict(BASE_CFG, ui_backoff_seconds=30)
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        self.assertEqual(r.ui_backoff_seconds(cfg), 0, '正常时不该退避')
        r.ui_down_since = time.time()
        self.assertEqual(r.ui_backoff_seconds(cfg), 30)
        r.ui_down_since = time.time() - 700
        self.assertEqual(r.ui_backoff_seconds(cfg), 0, '太久之前的不算数')

    def test_link_fetch_respects_total_budget(self):
        """抓网页要有总预算：单 URL 最坏 40s，一条两个链接的消息能卡死一轮回复。"""
        cfg = dict(BASE_CFG, links={'enabled': True, 'max_urls': 3, 'max_bytes': 1000,
                                    'max_chars': 500, 'timeout': 1,
                                    'total_budget_seconds': 0.2})
        calls = []

        def slow_fetch(url, links_cfg):
            calls.append(url)
            time.sleep(0.25)
            return {'url': url, 'status': 'read', 'untrusted_text': 'x'}

        msg = {'text': '看这个 https://a.example/1 还有 https://b.example/2 和 https://c.example/3'}
        with patch('resident.fetch_public_text', side_effect=slow_fetch):
            res = resident_mod.gather_sources([msg], cfg)
        self.assertEqual(len(calls), 1, '预算用完就不该再抓下一个')
        self.assertEqual([r['status'] for r in res],
                         ['read', 'skipped_budget', 'skipped_budget'])

    def test_seen_persists_only_when_something_new(self):
        """签名没变就别写盘：每 4 秒写一次 2.5KB 纯属浪费（笔记本还在跑通宵）。"""
        cfg = dict(BASE_CFG, watch_chats=['家庭群'], group_whitelist=['家庭群'])
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.nav = FakeNavigator(ui)
        bub = {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': False,
               'bbox': [80, 100, 200, 140], 'signature': 'sig-fixed'}
        writes = []
        r._persist_seen = lambda: writes.append(1)
        with patch('resident.CONFIG', FakeConfig(cfg)), \
             patch('visual_parse.extract_messages', return_value=[bub]):
            r.observe_one(cfg, ui, model, '家庭群', ui.capture())   # 建基线 → 写一次
            self.assertEqual(len(writes), 1)
            ui.change()                                             # 画面变了…
            r.observe_one(cfg, ui, model, '家庭群', ui.capture())   # …但签名没变
        self.assertEqual(len(writes), 1, '没有新签名就不该再写盘')

    def test_seen_keeps_most_recent_signatures(self):
        """裁剪"已见"要按最近保留：无序 set 会随机丢掉最近的消息，导致重复回一遍。"""
        r = make_resident(BASE_CFG)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        seen = {}
        for i in range(1000):
            r._note_seen(seen, ['sig-%04d' % i], keep=10)
        self.assertLessEqual(len(seen), 20, '内存上限 = keep*2')
        self.assertGreaterEqual(len(seen), 10)
        self.assertIn('sig-0999', seen, '最新的必须在')
        self.assertNotIn('sig-0000', seen, '最老的应被裁掉')
        self.assertEqual(list(seen)[-1], 'sig-0999', 'dict 保序=保时间序')

    def test_frame_changed_requeues_message(self):
        """生成期间画面整个变了：摘掉"已见"标记，下一轮重新当新消息回——不能吞掉。"""
        cfg = dict(BASE_CFG, watch_chats=[], group_whitelist=['家庭群'])
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.nav = FakeNavigator(ui)
        payload = json.dumps({'messages': [
            {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': True,
             'bbox': [80, 100, 200, 140], 'signature': 'sig-1'}], 'want_search': False})
        r.quota.enqueue('group:家庭群', 0, payload)
        r.last_frame['group:家庭群'] = Image.new('RGB', (735, 512), (0, 0, 0))
        r.seen_signatures['group:家庭群'] = dict.fromkeys(['sig-1'])
        with patch('resident.WeChatUI', return_value=ui), \
             patch('resident.StepPlan', return_value=model), \
             patch('resident.CONFIG', FakeConfig(cfg)), \
             patch('resident.frames_similar', return_value=False):
            r.process_queue(cfg, ui, model)
        self.assertNotIn('sig-1', r.seen_signatures['group:家庭群'],
                         '要摘掉已见标记，下一轮才能重新看到')
        state = r.db.execute("SELECT state FROM queue ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertEqual(state, 'CHANGED_RETRY')
        self.assertEqual(r.changed_retries.get('group:家庭群'), 1)

    def test_stale_last_frame_does_not_block_reply(self):
        """会话平静时 observe_one 不会刷新 last_frame：不能拿旧帧判"生成期间变了"。

        实测这个误判会把已经生成好的回复丢掉（合成任务连续两次 CHANGED_RETRY）。
        """
        cfg = dict(BASE_CFG, watch_chats=[], group_whitelist=['家庭群'])
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.nav = FakeNavigator(ui)
        payload = json.dumps({'messages': [
            {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': True,
             'bbox': [80, 100, 200, 140], 'signature': 'sig-1'}], 'want_search': False})
        r.quota.enqueue('group:家庭群', 0, payload)
        r.last_frame['group:家庭群'] = Image.new('RGB', (735, 512), (0, 0, 0))  # 旧帧
        with patch('resident.WeChatUI', return_value=ui), \
             patch('resident.StepPlan', return_value=model), \
             patch('resident.CONFIG', FakeConfig(cfg)):
            r.process_queue(cfg, ui, model)
        state = r.db.execute("SELECT state FROM queue ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertEqual(state, 'SUBMITTED')

    def test_ui_unavailable_defers_without_consuming_retries(self):
        """UI 不可用（客户端重启/登录窗）：消息留队列、不吃重试次数，UI 回来照发。"""
        cfg = dict(BASE_CFG, watch_chats=[], group_whitelist=['家庭群'],
                   max_send_retries=2)
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()

        class DownNavigator(FakeNavigator):
            def __init__(self, ui):
                super().__init__(ui)
                self.down = True
            def switch_to(self, name, use_cache=True):
                if self.down:
                    from wechat_ui import UIUnavailable
                    raise UIUnavailable('主窗口不唯一或未登录；禁止发送')
                return super().switch_to(name, use_cache)

        nav = DownNavigator(ui)
        r.nav = nav
        payload = json.dumps({'messages': [
            {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': True,
             'bbox': [80, 100, 200, 140], 'signature': 'sig-1'}], 'want_search': False})
        r.quota.enqueue('group:家庭群', 0, payload)
        with patch('resident.WeChatUI', return_value=ui), \
             patch('resident.StepPlan', return_value=model), \
             patch('resident.CONFIG', FakeConfig(cfg)), \
             patch('visual_parse.extract_messages', return_value=[]):
            for _ in range(4):        # 连续 4 轮不可用，超过 max_send_retries=2
                r.cycle(cfg)
            self.assertEqual(r.quota.depth(), 1, '消息必须一直在队列里')
            self.assertEqual(model.calls, [], '不该花模型调用')
            self.assertEqual([t for t in ui.sent_texts if isinstance(t, tuple)], [])
            nav.down = False          # 客户端回来了
            r.last_frame['group:家庭群'] = ui.chat_image(ui.verify_target(ui.capture()))
            for _ in range(3):
                r.cycle(cfg)
        sent = [t for t in ui.sent_texts if isinstance(t, tuple)]
        self.assertEqual(len(sent), 1, 'UI 回来后照发')
        self.assertEqual(r.quota.depth(), 0)

    def test_switch_failure_is_retried_then_succeeds(self):
        """一过性切换失败不能把消息丢掉：重新入队重试，成功照发。"""
        cfg = dict(BASE_CFG, watch_chats=[], group_whitelist=['家庭群'],
                   max_send_retries=2)
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.nav = FlakyNavigator(ui)
        payload = json.dumps({'messages': [
            {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': True,
             'bbox': [80, 100, 200, 140], 'signature': 'sig-1'}], 'want_search': False})
        r.quota.enqueue('group:家庭群', 0, payload)
        r.last_frame['group:家庭群'] = ui.chat_image(ui.capture())
        with patch('resident.WeChatUI', return_value=ui), \
             patch('resident.StepPlan', return_value=model), \
             patch('resident.CONFIG', FakeConfig(cfg)), \
             patch('visual_parse.extract_messages', return_value=[]):
            for _ in range(3):
                r.cycle(cfg)
        sent = [t for t in ui.sent_texts if isinstance(t, tuple)]
        self.assertEqual(len(sent), 1, '重试后应该发出去')
        rows = [x[0] for x in r.db.execute("SELECT state FROM queue ORDER BY id")]
        self.assertIn('SWITCH_RETRY', rows)
        self.assertEqual(r.quota.depth(), 0)

    def test_hot_items_pruned_per_source(self):
        """热榜每源只留最近 40 条：标题天天变，不清会一年涨几万行。"""
        r = make_resident(BASE_CFG)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        now = time.time()
        for i in range(60):
            r.db.execute("INSERT INTO hot_items(source,source_name,title,link,fetched)"
                         " VALUES('weibo_hot','微博热搜',?,?,?)",
                         ('标题%d' % i, 'https://x/%d' % i, now - (60 - i)))
        r.db.commit()
        r.feed._prune('weibo_hot')
        r.db.commit()
        rows = r.db.execute("SELECT title FROM hot_items WHERE source='weibo_hot'"
                            " ORDER BY fetched DESC").fetchall()
        self.assertEqual(len(rows), 40)
        self.assertEqual(rows[0][0], '标题59')      # 留的是最新的

    def test_health_ok_accepts_zero_heartbeat_age(self):
        """心跳刚写完时 age=0.0 是"很健康"，不能因为 0 是假值就误报不健康。"""
        import importlib.util
        root = os.path.dirname(os.path.abspath(__file__))
        spec = importlib.util.spec_from_file_location(
            'health_mod', os.path.join(root, 'wsl', 'health.py'))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        base = {'wechat-bot': 'active', 'wechat-stack': 'active', 'stop_file': False,
                'wechat': 'main 1021x740'}
        self.assertTrue(mod.health_ok(dict(base, heartbeat_age_s=0.0)))
        self.assertTrue(mod.health_ok(dict(base, heartbeat_age_s=12.5)))
        self.assertFalse(mod.health_ok(dict(base, heartbeat_age_s=200)))
        self.assertFalse(mod.health_ok(dict(base, heartbeat_age_s=None)))
        self.assertFalse(mod.health_ok(dict(base, stop_file=True, heartbeat_age_s=1.0)))
        self.assertFalse(mod.health_ok(dict(base, wechat='logged-out 292x396',
                                            heartbeat_age_s=1.0)))
        self.assertFalse(mod.health_ok(dict(base, **{'wechat-bot': 'inactive'},
                                            heartbeat_age_s=1.0)))
        # "活着但瞎了"：配置里要盯 2 个会话，上一轮一个都没看成 → 不健康
        self.assertFalse(mod.health_ok(dict(base, heartbeat_age_s=1.0,
                                            observed_chats=0, configured_chats=2)))
        self.assertTrue(mod.health_ok(dict(base, heartbeat_age_s=1.0,
                                           observed_chats=2, configured_chats=2)))
        self.assertTrue(mod.health_ok(dict(base, heartbeat_age_s=1.0,
                                           observed_chats=0, configured_chats=0)))

    def test_search_question_only_refreshes_one_source(self):
        """需要热榜时只补刷一个源，绝不整批刷新（整批最坏卡住 60 秒）。"""
        cfg = dict(BASE_CFG, watch_chats=['家庭群'], group_whitelist=['家庭群'],
                   hot_refresh_seconds=1)
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.nav = FakeNavigator(ui)
        now = time.time()
        from search import ROUTES
        for src, _route, _name in ROUTES:
            r.db.execute("INSERT OR REPLACE INTO hot_meta(source,fetched) VALUES(?,?)",
                         (src, now - 3600))
        r.db.commit()
        calls = []
        r.feed.refresh = lambda only_source=None, force=False: (calls.append(only_source), 1)[1]
        old = {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': False,
               'bbox': [80, 100, 200, 140], 'signature': 'sig-old'}
        msg = {'direction': 'in', 'kind': 'text', 'text': '最近有什么热搜', 'at_me': True,
               'bbox': [80, 200, 200, 240], 'signature': 'sig-hot'}
        with patch('resident.CONFIG', FakeConfig(cfg)), \
             patch('visual_parse.extract_messages', return_value=[old]):
            r.observe_one(cfg, ui, model, '家庭群', ui.capture())   # 先建基线
        ui.change()
        with patch('resident.CONFIG', FakeConfig(cfg)), \
             patch('visual_parse.extract_messages', return_value=[old, msg]):
            r.observe_one(cfg, ui, model, '家庭群', ui.capture())
        self.assertEqual(len(calls), 1, '只准补一个源')
        self.assertTrue(calls[0], '补的是具体某个源，不是整批')

    def test_hot_rotation_skips_dead_source(self):
        """拉不到的源也要记一笔"试过了"，否则轮转永远盯着它（zhihu 实测不可用）。"""
        cfg = dict(BASE_CFG, hot_refresh_seconds=1)
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        now = time.time()
        from search import ROUTES
        for src, _route, _name in ROUTES:
            r.db.execute("INSERT OR REPLACE INTO hot_meta(source,fetched) VALUES(?,?)",
                         (src, now))
        r.db.execute("INSERT OR REPLACE INTO hot_meta(source,fetched) VALUES('douyin_hot',?)",
                     (now - 9999,))
        r.db.commit()
        # 让抓取直接失败（不去碰外网），模拟"这个源在这几个实例上都拉不到"
        r.feed._fetch = lambda url: (_ for _ in ()).throw(OSError('offline'))
        r.hot_checked = 0
        r.hot_cycle(cfg)                    # 抓取失败 → 记一笔"试过了"
        stamp = r.db.execute("SELECT fetched FROM hot_meta WHERE source='douyin_hot'"
                             ).fetchone()[0]
        self.assertGreater(stamp, now - 30, '失败也要记尝试时间，否则永远盯着死源')
        called = []
        r.feed.refresh = lambda only_source=None, force=False: (called.append(only_source), 1)[1]
        r.hot_checked = 0
        r.hot_cycle(cfg)
        self.assertNotEqual(called, ['douyin_hot'], '下一轮该换别的源')

    def test_stop_during_cycle_defers_instead_of_dropping(self):
        """急停落在处理中间：消息要留回队列，不丢也不白花模型调用。"""
        cfg = dict(BASE_CFG, watch_chats=[], group_whitelist=['家庭群'])
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.nav = FakeNavigator(ui)
        payload = json.dumps({'messages': [
            {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': True,
             'bbox': [80, 100, 200, 140], 'signature': 'sig-1'}], 'want_search': False})
        r.quota.enqueue('group:家庭群', 0, payload)
        r.stop.write_text('stop', encoding='utf-8')      # 模拟急停已经生效
        with patch('resident.WeChatUI', return_value=ui), \
             patch('resident.StepPlan', return_value=model), \
             patch('resident.CONFIG', FakeConfig(cfg)):
            r.process_queue(cfg, ui, model)
        self.assertEqual([t for t in ui.sent_texts if isinstance(t, tuple)], [],
                         '急停期间不能发')
        self.assertEqual(model.calls, [], '急停期间不该花模型调用')
        self.assertEqual(r.quota.depth(), 1, '消息要留在队列里，不能丢')

    def test_degraded_poll_triggers_ui_recovery_once(self):
        """观察失败要自救一次（微信拉前台 + Esc 浮层），且 120 秒内不重复。"""
        cfg = dict(BASE_CFG, watch_chats=['家庭群'], group_whitelist=['家庭群'])
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.nav = FakeNavigator(ui)
        calls = []
        ui.activate = lambda: calls.append('activate')
        with patch('resident.WeChatUI', return_value=ui), \
             patch('resident.StepPlan', return_value=model), \
             patch('resident.CONFIG', FakeConfig(cfg)), \
             patch('visual_parse.extract_messages', return_value=[]):
            r.last_poll = {'outcomes': [{'state': 'observe_degraded'}]}
            r.cycle(cfg)
            self.assertIn('activate', calls)
            r.last_poll = {'outcomes': [{'state': 'observe_degraded'}]}
            r.cycle(cfg)
        self.assertEqual(calls.count('activate'), 1, '120 秒内不重复自救')

    def test_reply_attaches_at_most_two_images(self):
        """回复只挂最近 2 张时间线图片（实测挂 6 张多花 7 秒）。"""
        tmp = tempfile.mkdtemp()
        paths = []
        for i in range(6):
            p = Path(tmp) / ('pic%d.png' % i)
            Image.new('RGB', (40, 40), (10 * i, 200, 100)).save(p)
            paths.append(str(p))
        cfg = dict(BASE_CFG, reply_image_limit=2)
        sp = multimodal_mod.StepPlan(cfg)
        captured = {}
        def fake_call(messages, max_tokens=1800, model=None):
            captured['messages'] = messages
            return '好的呀'
        timeline = [{'direction': 'in', 'kind': 'image', 'text': '', 'image_path': p} for p in paths]
        with patch.object(sp, 'call', side_effect=fake_call):
            # 新消息本身是图片时才会挂时间线图片（纯文字消息挂旧图要慢 4 倍）
            sp.reply([{'direction': 'in', 'kind': 'image', 'text': ''}], [], [],
                     chat_context={'style': '', 'facts': [], 'timeline': timeline})
        parts = captured['messages'][-1]['content']
        images = [p for p in parts if isinstance(p, dict) and p.get('type') == 'image_url']
        self.assertEqual(len(images), 2)
        # 挂的是最新的两张，不是最老的
        self.assertIn(image_data(Image.open(paths[-1]).convert('RGB')),
                      images[-1]['image_url']['url'])

    def test_hourly_reply_cap_defers_message(self):
        """一小时内回够上限就先不发（防刷屏/防机器人互刷），消息留在队列里。"""
        cfg = dict(BASE_CFG, watch_chats=[], group_whitelist=['家庭群'],
                   max_replies_per_hour=1)
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.nav = FakeNavigator(ui)
        # 一小时里已经回过一条
        r.memory.record_turn('group:家庭群', 'assistant', '刚回过一条')
        payload = json.dumps({'messages': [
            {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': True,
             'bbox': [80, 100, 200, 140], 'signature': 'sig-1'}], 'want_search': False})
        r.quota.enqueue('group:家庭群', 0, payload)
        r.last_frame['group:家庭群'] = ui.chat_image(ui.verify_target(ui.capture()))
        with patch('resident.WeChatUI', return_value=ui), \
             patch('resident.StepPlan', return_value=model), \
             patch('resident.CONFIG', FakeConfig(cfg)), \
             patch('visual_parse.extract_messages', return_value=[]):
            for _ in range(2):
                r.cycle(cfg)
        self.assertEqual([t for t in ui.sent_texts if isinstance(t, tuple)], [])
        self.assertEqual(r.quota.depth(), 1)          # 消息没被丢
        self.assertEqual(model.calls, [])             # 也没白花模型调用

    def test_transient_model_failure_is_retried(self):
        """模型临时抖动（网络/超时）不能把消息丢掉：重试后要回出去。"""
        cfg = dict(BASE_CFG, watch_chats=[], group_whitelist=['家庭群'],
                   max_send_retries=2, retry_backoff_seconds=0)
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui = FakeWeChatUI()

        class FlakyModel(FakeModel):
            def __init__(self):
                super().__init__()
                self.calls = 0
            def reply(self, *a, **k):
                self.calls += 1
                if self.calls == 1:
                    raise OSError('connection reset by peer')
                return '好的呀'

        model = FlakyModel()
        r.nav = FakeNavigator(ui)
        payload = json.dumps({'messages': [
            {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': True,
             'bbox': [80, 100, 200, 140], 'signature': 'sig-1'}], 'want_search': False})
        r.quota.enqueue('group:家庭群', 0, payload)
        r.last_frame['group:家庭群'] = ui.chat_image(ui.verify_target(ui.capture()))
        with patch('resident.WeChatUI', return_value=ui), \
             patch('resident.StepPlan', return_value=model), \
             patch('resident.CONFIG', FakeConfig(cfg)), \
             patch('visual_parse.extract_messages', return_value=[]):
            for _ in range(3):
                r.cycle(cfg)
        sent = [t for t in ui.sent_texts if isinstance(t, tuple)]
        self.assertEqual(len(sent), 1, '重试后必须发出去')
        self.assertEqual(model.calls, 2)
        retried = r.db.execute('SELECT count(*) FROM queue WHERE state=?',
                               ('RETRY_TRANSIENT',)).fetchone()[0]
        self.assertEqual(retried, 1)
        self.assertEqual(r.quota.depth(), 0)

    def test_maintain_prunes_old_media(self):
        """过期媒体裁图会被清掉、新的留着（常驻机器人不能无限涨磁盘）。"""
        cfg = dict(BASE_CFG, maintain_seconds=1, media_keep_days=1)
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        base = Path(resident_mod.STATE) / 'media' / 'inbox' / 'group:家庭群'
        base.mkdir(parents=True, exist_ok=True)
        old, new = base / 'old.png', base / 'new.png'
        old.write_bytes(b'x' * 16)
        new.write_bytes(b'y' * 16)
        past = time.time() - 3 * 86400
        os.utime(old, (past, past))
        r.maintained_at = 0
        r.maintain_cycle(cfg)
        self.assertFalse(old.exists(), '过期裁图要删')
        self.assertTrue(new.exists(), '新裁图要留')
        r.maintain_cycle(cfg)          # 幂等：短时间内不会再跑

    def test_scrolling_media_is_not_replied_twice(self):
        """同一张图滚动后裁切不同、签名变了，也不能当成新消息再回一遍。"""
        cfg = dict(BASE_CFG, watch_chats=['家庭群'], group_whitelist=['家庭群'])
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.nav = FakeNavigator(ui)
        old = {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': False,
               'bbox': [80, 100, 200, 140], 'signature': 'sig-old'}
        pic1 = {'direction': 'in', 'kind': 'unread', 'text': '', 'description': '',
                'at_me': False, 'bbox': [300, 200, 420, 290], 'signature': 'in:aaa'}
        pic2 = dict(pic1, signature='in:bbb', bbox=[300, 194, 420, 284])   # 滚了一点点
        with patch('resident.CONFIG', FakeConfig(cfg)):
            with patch('visual_parse.extract_messages', return_value=[old]):
                r.observe_one(cfg, ui, model, '家庭群', ui.capture())
            ui.change()
            with patch('visual_parse.extract_messages', return_value=[old, pic1]):
                first = r.observe_one(cfg, ui, model, '家庭群', ui.capture())
            ui.change()
            with patch('visual_parse.extract_messages', return_value=[old, pic2]):
                second = r.observe_one(cfg, ui, model, '家庭群', ui.capture())
        self.assertTrue(first, '新图片应该入队')
        self.assertFalse(second, '同一张图滚动后不能当成新消息再入队')
        self.assertEqual(r.quota.depth(), 1)

    def test_busy_chat_still_replies(self):
        """聊天区持续轻微变化时仍然要处理新消息并回复（不能永久 debouncing）。"""
        cfg = dict(BASE_CFG, watch_chats=['家庭群'], group_whitelist=['家庭群'])
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = BusyUI(), FakeModel()
        r.nav = FakeNavigator(ui)
        msg_a = {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': False,
                 'bbox': [80, 100, 200, 140], 'signature': 'sig-a'}
        msg_b = {'direction': 'in', 'kind': 'text', 'text': '吃了吗', 'at_me': True,
                 'bbox': [80, 200, 200, 240], 'signature': 'sig-b'}
        with patch('resident.WeChatUI', return_value=ui), \
             patch('resident.StepPlan', return_value=model):
            with patch('resident.CONFIG', FakeConfig(cfg)), \
                 patch('visual_parse.extract_messages', return_value=[msg_a]):
                r.cycle(cfg)
            with patch('resident.CONFIG', FakeConfig(cfg)), \
                 patch('visual_parse.extract_messages', return_value=[msg_a, msg_b]):
                for _ in range(3):
                    r.cycle(cfg)
        sent = [t for t in ui.sent_texts if isinstance(t, tuple)]
        self.assertTrue(sent, '画面一直在动也要能回')

    def test_burst_sends_up_to_budget_in_one_cycle(self):
        """成串消息：一轮按 max_sends_per_cycle 连发，不再一轮只发一条。"""
        cfg = dict(BASE_CFG, watch_chats=[], group_whitelist=['Agent 聊天测试群'],
                   concurrency={'max_watch_chats': 4, 'max_sends_per_cycle': 2,
                                'queue_yield_after': 3})
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.nav = FakeNavigator(ui)
        payload = json.dumps({'messages': [
            {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': True,
             'bbox': [80, 100, 200, 140], 'signature': 'sig-1'}], 'want_search': False})
        r.quota.enqueue('group:Agent 聊天测试群', 0, payload)
        r.quota.enqueue('direct:很帅的年糕', 1, payload)
        # 队列项带着"入队时的画面指纹"，发送前会比对（防发错窗）；这里补上基线
        snap = ui.chat_image(ui.verify_target(ui.capture()))
        r.last_frame['group:Agent 聊天测试群'] = snap
        r.last_frame['direct:很帅的年糕'] = snap
        with patch('resident.WeChatUI', return_value=ui), \
             patch('resident.StepPlan', return_value=model), \
             patch('resident.CONFIG', FakeConfig(cfg)), \
             patch('visual_parse.extract_messages', return_value=[]):
            r.cycle(cfg)
        sent = [t for t in ui.sent_texts if isinstance(t, tuple)]
        self.assertEqual(len(sent), 2)        # 一轮连发两条
        self.assertEqual(r.quota.depth(), 0)  # 队列清空
        self.assertEqual(r.db.execute('SELECT count(*) FROM deliveries').fetchone()[0], 2)

    def test_budget_one_sends_single_per_cycle(self):
        """max_sends_per_cycle=1 时一轮只发一条（预算配置真的生效）。"""
        cfg = dict(BASE_CFG, watch_chats=[], group_whitelist=['Agent 聊天测试群'],
                   concurrency={'max_watch_chats': 4, 'max_sends_per_cycle': 1,
                                'queue_yield_after': 3})
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.nav = FakeNavigator(ui)
        payload = json.dumps({'messages': [
            {'direction': 'in', 'kind': 'text', 'text': '在吗', 'at_me': True,
             'bbox': [80, 100, 200, 140], 'signature': 'sig-1'}], 'want_search': False})
        r.quota.enqueue('group:Agent 聊天测试群', 0, payload)
        r.quota.enqueue('direct:很帅的年糕', 1, payload)
        snap = ui.chat_image(ui.verify_target(ui.capture()))
        r.last_frame['group:Agent 聊天测试群'] = snap
        r.last_frame['direct:很帅的年糕'] = snap
        with patch('resident.WeChatUI', return_value=ui), \
             patch('resident.StepPlan', return_value=model), \
             patch('resident.CONFIG', FakeConfig(cfg)), \
             patch('visual_parse.extract_messages', return_value=[]):
            r.cycle(cfg)
        sent = [t for t in ui.sent_texts if isinstance(t, tuple)]
        self.assertEqual(len(sent), 1)        # 只发一条
        self.assertEqual(r.quota.depth(), 1)  # 另一条留到下一轮

    def test_priority_order(self):
        """群@优先于私信优先于群普通（三个不同会话，避免同会话新代旧）。"""
        r = make_resident(BASE_CFG)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        r.quota.enqueue('group:家庭群', 2, json.dumps({'messages': [], 'want_search': False}))
        r.quota.enqueue('direct:很帅的年糕', 1, json.dumps({'messages': [], 'want_search': False}))
        r.quota.enqueue('group:同学群', 0, json.dumps({'messages': [], 'want_search': False}))
        order = []
        for _ in range(3):
            row = r.quota.claim()
            order.append(row[2])
            r.quota.finish(row[0], 'DONE')
        self.assertEqual(order, [0, 1, 2])

    def test_quota_rest_remind_and_resume(self):
        """撞限额：高优先级发休息提醒+进等待；额度恢复后自动唤醒。"""
        cfg = dict(BASE_CFG)
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.nav = FakeNavigator(ui)
        try:
            # 用光 5h 额度（limit=5）
            for _ in range(5):
                r.quota.consume(1)
            # 避免 learn_cycle 里真模型打真实 API
            import resident as _rm
            _orig_step = _rm.StepPlan
            _rm.StepPlan = lambda cfg, db=None: model      # resident 现在传 (cfg, db)
            payload = json.dumps({'messages': [{'direction': 'in', 'text': '在吗'}], 'want_search': False})
            qid = r.quota.enqueue('direct:很帅的年糕', 1, payload)
            # 处理 → 撞限额 → 发提醒 → WAITING_QUOTA
            with patch('resident.CONFIG', FakeConfig(cfg)):
                r.process_queue(cfg, ui, model)
            reminded = [t for t in ui.sent_texts if isinstance(t, tuple) and '休息' in t[1]]
            self.assertEqual(len(reminded), 1)
            self.assertIn('请等待', reminded[0][1])
            self.assertEqual(r.quota.waiting_count(), 1)
            # 清掉额度记录模拟恢复 → cycle 开头应唤醒
            r.db.execute('DELETE FROM usage'); r.db.commit()
            with patch('resident.CONFIG', FakeConfig(cfg)), \
                 patch('resident.WeChatUI', return_value=ui), \
                 patch('visual_parse.extract_messages', return_value=[]):
                r.cycle(cfg)
            self.assertEqual(r.quota.waiting_count(), 0)
            self.assertIn(('SENT', model.reply_text), ui.sent_texts)
            self.assertEqual(r.db.execute('SELECT count(*) FROM deliveries').fetchone()[0], 1)
        finally:
            _rm.StepPlan = _orig_step
            stop_patches(r)

    def test_memory_learning_trigger(self):
        """攒够 20 条新消息 → 触发风格学习（花 1 次模型调用）。"""
        cfg = dict(BASE_CFG)
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.memory.note_messages('direct:很帅的年糕', 20, 'direct', '很帅的年糕')
        r.memory.record_turn('direct:很帅的年糕', 'user', '今天想玩塞尔达')
        self.assertTrue(r.memory.needs_learn('direct:很帅的年糕'))
        r.learn_cycle(cfg, model)
        self.assertFalse(r.memory.needs_learn('direct:很帅的年糕'))
        ctx = r.memory.context_for('direct:很帅的年糕')
        self.assertEqual(ctx['style'], '软萌')

    def test_moment_draft_generated(self):
        """到点生成朋友圈草稿（mock 生图）。"""
        cfg = dict(BASE_CFG, moments={'enabled': True, 'min_days': 2, 'max_days': 3,
                                      'max_chars': 300, 'with_image': False})
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.moment_cycle(cfg, model)
        rows = r.db.execute("SELECT state FROM moments WHERE state='DRAFT'").fetchall()
        self.assertEqual(len(rows), 1)

    def test_moment_publish_requires_human_token(self):
        """没有人审令牌，常驻机器人绝不发布朋友圈（一个 xdotool 都不发）。"""
        cfg = dict(BASE_CFG, automation={'enabled': True, 'allow_moments': True},
                   moments={'enabled': True, 'min_days': 2, 'max_days': 3,
                            'max_chars': 300, 'with_image': False})
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.moment_cycle(cfg, model)
        self.assertEqual(
            r.db.execute("SELECT count(*) FROM moments WHERE state='DRAFT'").fetchone()[0], 1)
        r.moment_publish_cycle(cfg, ui, model)
        self.assertEqual(r.release.state_dir, Path(r._tmp))
        self.assertEqual([c for c in ui.commands if c and c[0] == 'xdotool'], [])
        self.assertEqual(
            r.db.execute("SELECT count(*) FROM moments WHERE state='PUBLISHED'").fetchone()[0], 0)

    def test_moment_publish_uncalibrated_refuses(self):
        """有令牌但坐标未标定 → 记录 uncalibrated，仍然一个点都不发。"""
        import moment_release as mr
        cfg = dict(BASE_CFG, automation={'enabled': True, 'allow_moments': True},
                   moments={'enabled': True, 'min_days': 2, 'max_days': 3,
                            'max_chars': 300, 'with_image': False})
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.moment_cycle(cfg, model)
        mid = r.db.execute("SELECT id FROM moments WHERE state='DRAFT'").fetchone()[0]
        with patch.object(mr, 'STATE', Path(r._tmp)):
            rel = mr.MomentRelease(r.db, ui, composer=r.moments, coords={}, cfg=cfg['moments'])
            rel.approve(mid)
            r.release = rel
            r.moment_publish_cycle(cfg, ui, model)
            status = json.loads((Path(r._tmp) / 'status.json').read_text())
        self.assertEqual(status['state'], 'moment_publish_uncalibrated')
        self.assertEqual([c for c in ui.commands if c and c[0] == 'xdotool'], [])
        self.assertEqual(
            r.db.execute("SELECT count(*) FROM moments WHERE state='PUBLISHED'").fetchone()[0], 0)
        self.assertEqual(rel.approved_id(), mid)   # 令牌保留，标定后可原样重试

    def test_moment_publish_blocked_by_master_switch(self):
        """automation.allow_moments=false（朋友圈总闸关闭）：草稿+人审令牌都在位也不发布。

        令牌只代表“内容被人工确认过”，不代表“现在就发朋友圈”；总闸是独立的一层。
        """
        import moment_release as mr
        cfg = dict(BASE_CFG, automation={'enabled': True, 'allow_moments': False},
                   moments={'enabled': True, 'min_days': 2, 'max_days': 3,
                            'max_chars': 300, 'with_image': False})
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        ui, model = FakeWeChatUI(), FakeModel()
        r.moment_cycle(cfg, model)
        mid = r.db.execute("SELECT id FROM moments WHERE state='DRAFT'").fetchone()[0]
        with patch.object(mr, 'STATE', Path(r._tmp)):
            rel = mr.MomentRelease(r.db, ui, composer=r.moments, coords={}, cfg=cfg['moments'])
            rel.approve(mid)
            r.moment_publish_cycle(cfg, ui, model)
        self.assertEqual([c for c in ui.commands if c and c[0] == 'xdotool'], [])
        self.assertEqual(
            r.db.execute("SELECT count(*) FROM moments WHERE state='PUBLISHED'").fetchone()[0], 0)
        self.assertEqual(rel.approved_id(), mid)   # 令牌保留：开闸后仍可发布

    def test_chat_key_isolation(self):
        """不同会话 chat_key 隔离。"""
        cfg = {'target_chat': 'A', 'group_whitelist': ['B群'],
               'direct_blacklist': [], 'group_policy': 'whitelist',
               'direct_policy': 'blacklist'}
        self.assertEqual(chat_key_of(cfg, 'A'), 'direct:A')
        self.assertEqual(chat_key_of(cfg, 'B群'), 'group:B群')
        self.assertIsNone(chat_key_of(cfg, '陌生人群'))  # 非白名单群不收
    def test_direct_blacklist(self):
        """私信黑名单制：黑名单内拒绝，其余私信放行。"""
        cfg = {'target_chat': 'A', 'group_whitelist': [], 'direct_blacklist': ['推销号']}
        self.assertEqual(chat_key_of(cfg, '新朋友', chat_type='direct'), 'direct:新朋友')
        self.assertIsNone(chat_key_of(cfg, '推销号'))
    def test_empty_whitelist_no_group(self):
        cfg = {'target_chat': 'A', 'group_whitelist': [], 'direct_blacklist': []}
        self.assertEqual(chat_key_of(cfg, '任何人', chat_type='direct'), 'direct:任何人')


if __name__ == '__main__':
    unittest.main(verbosity=2)
