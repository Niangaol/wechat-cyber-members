"""Keep the real verify_target/send_text code; fake only OS input and screenshots."""
import json
import unittest
from unittest.mock import patch
from PIL import Image
from test_integration import BASE_CFG, FakeConfig, FakeModel, FakeNavigator, make_resident, stop_patches
from wechat_ui import WeChatUI, SafetyError
from resident import fingerprint

class SimulatedUI(WeChatUI):
    def __init__(self, cfg, title):
        super().__init__(cfg)
        self.title = title
        self.clipboard = 'old clipboard'
        self.draft = ''
        self.sent = []
        self.keys = []
        self.wid = 'fake'
    def capture(self):
        return Image.new('RGB', (1021, 740), (237, 237, 237))
    def ocr(self, image, psm=6):
        return self.title if psm == 7 else self.draft
    def run(self, args, data=None, timeout=12):
        return b''  # 模拟 OS 层：所有 xdotool/tesseract 都不真实执行
    def clipboard_read(self):
        return self.clipboard
    def clipboard_write(self, text):
        self.clipboard = text
    def key(self, key):
        self.keys.append(key)
        if key == 'ctrl+v': self.draft = self.clipboard
        if key == 'ctrl+c': self.clipboard = self.draft
        if key == 'Delete': self.draft = ''      # ctrl+a + Delete 是清空输入框的可靠方式
        if key == 'Return':
            self.sent.append(self.draft)
            self.draft = ''

class BindingTests(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(BASE_CFG, group_whitelist=['测试群'])
        self.r = make_resident(self.cfg)
        self.addCleanup(stop_patches, self.r)
        self.addCleanup(self.r.db.close)
        self.ui = SimulatedUI(self.cfg, '测试群(4)')
        self.r.nav = FakeNavigator(self.ui)
        self.model = FakeModel()
        self.ck = 'group:测试群'
        # 发送前比对用的是"观察时的聊天区截图"，不再是全等指纹
        self.r.last_frame[self.ck] = self.ui.chat_image(self.ui.capture())
        sleeper = patch('wechat_ui.time.sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)
    def enqueue(self):
        return self.r.quota.enqueue(self.ck, 0, json.dumps({'messages': [{'text': '你好'}], 'want_search': False}))
    def process(self, config=None):
        with patch('resident.CONFIG', config or FakeConfig(self.cfg)):
            self.r.process_queue(self.cfg, self.ui, self.model)
    def state(self, qid):
        return self.r.db.execute('SELECT state FROM queue WHERE id=?', (qid,)).fetchone()[0]
    def test_unsafe_model_reply_is_not_submitted(self):
        """没过安全闸的回复绝不发出去；会重生成一次，第二次仍不过才放弃。"""
        qid = self.enqueue()
        self.model.reply_text = '推荐股票稳赚'
        self.process()
        self.assertEqual(self.ui.sent, [])
        self.assertEqual(self.state(qid), 'UNSAFE_RETRY')
        # 第二次仍然不过 → 放弃（状态落到 UNSAFE_REPLY），依旧什么都没发
        retry_qid = self.r.db.execute('SELECT max(id) FROM queue').fetchone()[0]
        self.process()
        self.assertEqual(self.ui.sent, [])
        self.assertEqual(self.state(retry_qid), 'UNSAFE_REPLY')
        self.assertEqual(self.r.db.execute('SELECT count(*) FROM deliveries').fetchone()[0], 0)
    def test_group_only_config_without_default_direct(self):
        self.cfg.pop('target_chat')
        qid = self.enqueue()
        self.process()
        self.assertEqual(self.ui.sent, ['好的呀'])
        self.assertEqual(self.state(qid), 'SUBMITTED')
    def test_missing_default_requires_explicit_target(self):
        self.cfg.pop('target_chat')
        with self.assertRaises(SafetyError):
            self.ui.verify_target()
    def test_group_send_uses_task_not_default_direct(self):
        qid = self.enqueue()
        self.process()
        self.assertEqual(self.ui.sent, ['好的呀'])
        self.assertEqual(self.state(qid), 'SUBMITTED')
        self.assertEqual(self.ui.clipboard, 'old clipboard')
        self.assertEqual(self.ui.cfg['target_chat'], BASE_CFG['target_chat'])
    def test_wrong_title_during_model_generation_never_sends(self):
        qid = self.enqueue()
        def reply(*args, **kwargs):
            self.ui.title = '其他群(4)'
            return '不能发送'
        self.model.reply = reply
        self.process()
        self.assertEqual(self.ui.sent, [])
        self.assertNotIn('Return', self.ui.keys)
        self.assertNotEqual(self.state(qid), 'SUBMITTED')
    def test_revoked_group_before_generation_costs_no_model(self):
        qid = self.enqueue()
        self.process(FakeConfig(dict(self.cfg, group_whitelist=[])))
        self.assertEqual(self.model.calls, [])
        self.assertEqual(self.ui.sent, [])
        self.assertNotEqual(self.state(qid), 'SUBMITTED')
    def test_revoked_group_during_generation_never_sends(self):
        qid = self.enqueue()
        latest = FakeConfig(self.cfg)
        def reply(*args, **kwargs):
            latest._text = json.dumps(dict(self.cfg, group_whitelist=[]))
            return '不能发送'
        self.model.reply = reply
        self.process(latest)
        self.assertEqual(self.ui.sent, [])
        self.assertNotEqual(self.state(qid), 'SUBMITTED')
    def test_direct_blacklist_revocation_blocks(self):
        self.ck = 'direct:' + BASE_CFG['target_chat']
        self.ui.title = BASE_CFG['target_chat']
        qid = self.enqueue()
        self.process(FakeConfig(dict(self.cfg, direct_blacklist=[self.ui.title])))
        self.assertEqual(self.ui.sent, [])
        self.assertEqual(self.model.calls, [])
    def test_send_text_rechecks_target_before_return(self):
        original = self.ui.key
        def switch_after_readback(key):
            original(key)
            if key == 'ctrl+c': self.ui.title = '其他人'
        self.ui.key = switch_after_readback
        with self.assertRaises(SafetyError):
            self.ui.send_text('测试', expected_chat='测试群')
        self.assertNotIn('Return', self.ui.keys)
        self.assertEqual(self.ui.sent, [])
        self.assertEqual(self.ui.draft, '测试')
    def test_policy_revoked_after_readback_never_presses_return(self):
        qid = self.enqueue()
        latest = FakeConfig(self.cfg)
        original = self.ui.key
        def revoke(key):
            original(key)
            if key == 'ctrl+c':
                latest._text = json.dumps(dict(self.cfg, group_whitelist=[]))
        self.ui.key = revoke
        self.process(latest)
        self.assertNotIn('Return', self.ui.keys)
        self.assertEqual(self.ui.sent, [])
        self.assertNotEqual(self.state(qid), 'SUBMITTED')
    def test_stop_after_readback_never_presses_return(self):
        self.enqueue()
        original = self.ui.key
        def stop(key):
            original(key)
            if key == 'ctrl+c': self.r.stop.touch()
        self.ui.key = stop
        self.process()
        self.assertNotIn('Return', self.ui.keys)
        self.assertEqual(self.ui.sent, [])
    def test_quota_reminder_bound_to_group(self):
        qid = self.enqueue()
        for _ in range(self.cfg['limits']['window_5h']): self.r.quota.consume(0)
        self.process()
        self.assertEqual(len(self.ui.sent), 1)
        self.assertIn('休息', self.ui.sent[0])
        self.assertEqual(self.state(qid), 'WAITING_QUOTA')

if __name__ == '__main__': unittest.main()
