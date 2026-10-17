import sqlite3, sys, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent/'src'))
from moments_safe import is_safe, sanitize_for_moment, topic_allowed
from moments import MomentComposer

class SafeTests(unittest.TestCase):
    def test_banned_rejected(self):
        for bad in ['今天股市涨停了三支', '隔壁地震了要注意', '分享一个翻墙教程',
                    '这家店治病疗效好', '扫码领取红包', '投资建议：稳赚不赔']:
            ok, hits = is_safe(bad)
            self.assertFalse(ok, bad)
    def test_normal_passed(self):
        for good in ['红糖糍粑煎到脆响的那一秒最治愈', '海拉鲁的云跑得比谁都快',
                     '认识了一个会作诗的Agent朋友', '入秋后的风开始有形状了']:
            ok, _ = is_safe(good)
            self.assertTrue(ok, good)
    def test_sanitize_rejects_banned(self):
        with self.assertRaises(ValueError):
            sanitize_for_moment('今天买股票涨停了')
    def test_sanitize_rejects_long(self):
        with self.assertRaises(ValueError):
            sanitize_for_moment('甜' * 301)
    def test_sanitize_rejects_empty(self):
        with self.assertRaises(ValueError):
            sanitize_for_moment('   ')
    def test_sanitize_rejects_privacy(self):
        """朋友圈/评论是公开内容：手机号、密钥一律拦下（和私聊输出同一套判据）。"""
        for bad in ['加我微信 13800000000 聊', 'sk-abcdefgh12345678', '13800000000',
                    '联系我：13712345678']:
            with self.assertRaises(ValueError, msg=bad):
                sanitize_for_moment(bad, 200)
        # 正常内容不受影响
        self.assertEqual(sanitize_for_moment('今天拍了张云，像棉花糖', 200),
                         '今天拍了张云，像棉花糖')
    def test_topic_whitelist(self):
        self.assertTrue(topic_allowed('travel'))
        self.assertFalse(topic_allowed('politics'))
    def test_space_evasion_blocked(self):
        # 插入空格/零宽/标点规避黑名单的也必须拦下
        for ev in ['股 市', '股\u200b市', '恐-怖', '政 治', '毒品!']:
            ok, _ = is_safe(ev)
            self.assertFalse(ok, ev)
    def test_normal_text_still_passes(self):
        for good in ['红糖糍粑真好吃', '今天去爬山拍照了', '海拉鲁的云真好看']:
            ok, _ = is_safe(good)
            self.assertTrue(ok, good)

class FakeModel:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
    def call(self, messages, max_tokens=400):
        self.calls += 1
        return self.replies.pop(0) if self.replies else ' fallback 文本'

class ComposerTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.cfg = {'min_days': 2, 'max_days': 3, 'max_chars': 300, 'with_image': True}
    def test_due_initially(self):
        c = MomentComposer(self.db, FakeModel([]), self.cfg)
        self.assertTrue(c.due())
    def test_not_due_after_publish(self):
        c = MomentComposer(self.db, FakeModel([]), self.cfg)
        d = c.draft()
        c.mark_published(d['id'])
        self.assertFalse(c.due())
        self.assertAlmostEqual(c.last_published(), time.time(), delta=5)
    def test_due_after_interval(self):
        c = MomentComposer(self.db, FakeModel([]), self.cfg)
        d = c.draft(); c.mark_published(d['id'])
        c._set_meta('last_published', time.time() - 3.5*86400)
        self.assertTrue(c.due())
    def test_draft_safe_text(self):
        c = MomentComposer(self.db, FakeModel(['红糖冰粉沉下去的样子很好看']), self.cfg)
        d = c.draft()
        self.assertEqual(d['text'], '红糖冰粉沉下去的样子很好看')
    def test_draft_rejects_unsafe_then_retries(self):
        # 模型先输出危险内容，再输出安全内容：作废重挑后拿到安全的
        c = MomentComposer(self.db, FakeModel(['今天股市涨停啦', '海拉鲁的晚霞']), self.cfg)
        d = c.draft()
        self.assertEqual(d['text'], '海拉鲁的晚霞')
        # 危险草稿不能落库
        texts = [r[0] for r in self.db.execute('SELECT text FROM moments').fetchall()]
        self.assertNotIn('今天股市涨停啦', texts)
    def test_draft_all_unsafe_returns_none(self):
        c = MomentComposer(self.db, FakeModel(['股票', '地震', '翻墙', '病毒', '炒股']), self.cfg)
        self.assertIsNone(c.draft())
    def test_seed_no_repeat_until_exhausted(self):
        c = MomentComposer(self.db, FakeModel(['文本']*40), self.cfg)
        seeds = [c.draft()['seed'] for _ in range(10)]
        self.assertEqual(len(set(seeds)), len(seeds))
    def test_image_topics_flagged(self):
        c = MomentComposer(self.db, FakeModel(['风景真好']*30), self.cfg)
        d = c.draft()
        # 全部选题都配图（图文比纯文字更有设计感）
        self.assertTrue(d['need_image'])

if __name__ == '__main__':
    unittest.main(verbosity=2)
