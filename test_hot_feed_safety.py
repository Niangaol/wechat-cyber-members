import sqlite3, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent/'src'))
from search import HotFeed
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


if __name__ == '__main__':
    unittest.main()
