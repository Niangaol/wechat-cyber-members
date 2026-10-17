import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent/'src'))
from moments_collector import parse_cards, card_fingerprint, MomentsCollector
from moment_interact import MomentInbox
import sqlite3

SAMPLE = '''年糕Agent
今天在海拉鲁爬山，风景绝了
12分钟前
林铵杰
实验数据终于跑完了，感恩
1小时前
美丽生活分享群
妈：苏梅岛还是专门度假的
昨天'''

class ParseTests(unittest.TestCase):
    def test_parse_cards(self):
        cards = parse_cards(SAMPLE)
        self.assertEqual(len(cards), 3)
        self.assertEqual(cards[0]['author'], '年糕Agent')
        self.assertIn('海拉鲁', cards[0]['text'])
        self.assertEqual(cards[1]['author'], '林铵杰')
    def test_time_lines_excluded(self):
        cards = parse_cards(SAMPLE)
        for c in cards:
            self.assertNotIn('12分钟前', c['text'])
            self.assertNotIn('昨天', c['text'])
    def test_fingerprint_stable(self):
        c = {'author': '年糕', 'text': '你好 世界'}
        self.assertEqual(card_fingerprint(c), card_fingerprint({'author': ' 年糕 ', 'text': '你好  世界'}))
    def test_empty(self):
        self.assertEqual(parse_cards(''), [])

class FakeUI:
    def capture(self):
        from PIL import Image
        return Image.new('RGB', (550, 550), (255, 255, 255))
    def ocr(self, image, psm=6):
        return SAMPLE
    def run(self, args, data=None, timeout=12):
        return b''

class CollectorTests(unittest.TestCase):
    def test_collect_adds_to_inbox(self):
        inbox = MomentInbox(sqlite3.connect(':memory:'))
        added = MomentsCollector(FakeUI()).collect(inbox, screens=1)
        self.assertEqual(added, 3)
        self.assertEqual(inbox.pending_count(), 3)
    def test_collect_dedup(self):
        inbox = MomentInbox(sqlite3.connect(':memory:'))
        c = MomentsCollector(FakeUI())
        c.collect(inbox, screens=1)
        c.collect(inbox, screens=1)
        self.assertEqual(inbox.pending_count(), 3)

if __name__ == '__main__':
    unittest.main(verbosity=2)
