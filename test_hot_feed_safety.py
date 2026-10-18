import sqlite3, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent/'src'))
from search import HotFeed, needs_search
from moments_safe import is_safe, sanitize_for_moment

SAMPLE = [
    ('微博热搜', '习近平致信祝贺湖南大学建校100周年'),
    ('微博热搜', '日本误报9.9级地震'),
    ('微博热搜', '芒果真的拍了再见朋友'),
    ('B站热榜', '某UP主翻唱火遍全网'),
    ('知乎热榜', '如何评价最新款游戏手柄'),
]
SENSITIVE = ('习近平', '毛泽东', '周恩来', '地震', '疫情', '台独', '港独', '杀人', '炸弹')


class HotFeedSafetyTests(unittest.TestCase):
    def setUp(self):
        self.feed = HotFeed(sqlite3.connect(':memory:'))
        for i, (name, title) in enumerate(SAMPLE):
            self.feed._save('src%d' % i, name, title, 'https://example.com/%d' % i, 1.0)

    def test_relevant_filters_sensitive_titles(self):
        out = self.feed.relevant('今天有什么热搜', limit=10)
        titles = [o['title'] for o in out]
        for bad in SENSITIVE:
            self.assertFalse(any(bad in t for t in titles), '泄漏: ' + bad)

    def test_relevant_keeps_safe_titles(self):
        titles = [o['title'] for o in self.feed.relevant('游戏手柄', limit=10)]
        self.assertIn('如何评价最新款游戏手柄', titles)

    def test_empty_query_still_safe(self):
        for o in self.feed.relevant('', limit=10):
            self.assertTrue(is_safe(o['title'])[0])

    def test_blacklist_covers_political_names(self):
        for text in ['习近平', '毛泽东', '总理', '总书记', '国务院', '台湾', '新疆', '香港', '西藏']:
            with self.subTest(text=text):
                self.assertFalse(is_safe(text)[0], text)

    def test_blacklist_blocks_split_and_fullwidth(self):
        for text in ['政 治', '政🔥治', '政＿治', 'ｐｏｌｉｔｉｃａｌ政治'.replace('political', '')]:
            with self.subTest(text=text):
                self.assertFalse(is_safe(text)[0], text)

    def test_sanitize_rejects_sensitive_moment(self):
        with self.assertRaises(ValueError):
            sanitize_for_moment('今天看到习近平的新闻')


class TriggerTests(unittest.TestCase):
    """触发词表：决定一条消息要不要去联网查。

    2026-10-18 实机漏搜的复盘用例——群里问「dsv4.1flash1017 版本怎么样」，
    旧表一个字都没命中，机器人只能回"没查到具体信息"，搜索功能形同没接。
    """

    def test_real_miss_from_group_chat_now_triggers(self):
        self.assertTrue(needs_search('@年糕 Agent dsv4.1flash1017 版本怎么样'))

    def test_version_and_price_questions_trigger(self):
        for text in ['这游戏什么版本了', '现在多少钱', '价格多少', '参数怎么样',
                     '和上一代对比', '哪款更值得买', '哪个好', '求推荐', '这家靠谱吗',
                     '什么时候发布的', '更新了吗']:
            with self.subTest(text=text):
                self.assertTrue(needs_search(text), text)

    def test_plain_chat_does_not_trigger(self):
        for text in ['哈哈哈', '吃了吗', '我先去上课了', '好嘞', '晚安']:
            with self.subTest(text=text):
                self.assertFalse(needs_search(text), text)

    def test_old_words_still_work(self):
        for text in ['今天有什么热搜', '最新消息', '有什么新闻', '太火了']:
            with self.subTest(text=text):
                self.assertTrue(needs_search(text), text)


if __name__ == '__main__':
    unittest.main()
