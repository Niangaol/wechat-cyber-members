import sqlite3, sys, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent/'src'))
from quota import Quota, QuotaExceeded, PRIORITY_DIRECT, PRIORITY_GROUP_AT
from search import HotFeed, needs_search, clean

LIMITS = {'window_5h': 5, 'window_1d': 100}

class QuotaWaitTests(unittest.TestCase):
    def setUp(self):
        self.q = Quota(sqlite3.connect(':memory:'))
    def test_reset_zero_when_not_exceeded(self):
        self.q.consume(PRIORITY_DIRECT)
        self.assertEqual(self.q.next_reset_seconds(LIMITS), 0)  # 没超限不用等
    def test_reset_only_5h_exceeded(self):
        for _ in range(5):
            self.q.consume(PRIORITY_DIRECT)
        sec = self.q.next_reset_seconds(LIMITS)  # 5h 满(5/5)，1d 未满(5/100)
        self.assertTrue(5*3600 - 60 < sec <= 5*3600)
    def test_reset_both_exceeded_takes_later(self):
        tight = {'window_5h': 3, 'window_1d': 3}
        for _ in range(3):
            self.q.consume(PRIORITY_DIRECT)
        sec = self.q.next_reset_seconds(tight)  # 两个窗口都超：取最晚恢复的
        self.assertTrue(sec > 5*3600)
    def test_reset_zero_when_empty(self):
        self.assertEqual(self.q.next_reset_seconds(LIMITS), 0)
    def test_wait_and_requeue(self):
        qid = self.q.enqueue('c', PRIORITY_DIRECT, '{}')
        self.q.wait(qid)
        self.assertEqual(self.q.waiting_count(), 1)
        self.assertIsNone(self.q.claim())
        self.assertEqual(self.q.requeue_waiting(), 1)
        row = self.q.claim()
        self.assertEqual(row[0], qid)
    def test_waiting_not_superseded(self):
        q1 = self.q.enqueue('c', PRIORITY_DIRECT, 'old')
        self.q.wait(q1)
        self.q.enqueue('c', PRIORITY_DIRECT, 'new')
        self.assertEqual(self.q.waiting_count(), 1)
        self.assertEqual(self.q.depth(), 1)
    def test_no_remind_for_low_priority(self):
        # 群普通(2)不享受休息提醒——由 resident 逻辑决定，这里验证优先级常量差
        self.assertTrue(PRIORITY_GROUP_AT < PRIORITY_DIRECT)

class SearchTests(unittest.TestCase):
    def test_triggers(self):
        for t in ['最近有什么热搜', '今天有什么大新闻', '那个梗是什么意思', '吃什么瓜']:
            self.assertTrue(needs_search(t), t)
    def test_no_trigger(self):
        for t in ['你好', '帮我写个作业', '晚上吃啥', '1+1等于几']:
            self.assertFalse(needs_search(t), t)
    def test_clean_strips_html(self):
        self.assertEqual(clean('<b>热搜</b>第一<a href=x>链接</a>'), '热搜第一链接')
    def test_relevant_match_and_fallback(self):
        feed = HotFeed(sqlite3.connect(':memory:'))
        now = time.time()
        feed._save('s', '微博热搜', '某明星官宣恋情', 'http://x', now)
        feed._save('s', '微博热搜', '某歌手发布新专辑', 'http://y', now)
        hit = feed.relevant('明星')
        self.assertEqual(hit[0]['title'], '某明星官宣恋情')
        fallback = feed.relevant('完全不相关的词')
        self.assertEqual(len(fallback), 2)  # 命中不足退化为最新热榜
    def test_relevant_empty(self):
        self.assertEqual(HotFeed(sqlite3.connect(':memory:')).relevant('任何'), [])

if __name__ == '__main__':
    unittest.main(verbosity=2)
