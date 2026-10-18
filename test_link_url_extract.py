r"""URL 抽取回归：中文紧跟链接时不能把中文吞进 URL（微信侧与 QQ 侧同一条规则）。

背景（qq-core 在实现 QQ 链接阅读时发现）：微信侧老正则 [^\s<>"\u3000]+ 会把链接后面的
中文一起抠进去——"看这个 https://a/b，挺好的" 变成 "https://a/b，挺好的"，拿去请求必然 404。
两侧现在都用 ASCII 字符集，这里把行为钉死。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))

import resident as resident_mod                                     # noqa: E402
from qq.core import service as qq_service                           # noqa: E402

LINKS_CFG = {'enabled': True, 'max_urls': 3, 'max_bytes': 1000, 'max_chars': 500,
             'timeout': 1, 'total_budget_seconds': 5}


class WeChatUrlExtractionTests(unittest.TestCase):
    def gather(self, text):
        seen = []

        def fake_fetch(url, links_cfg):
            seen.append(url)
            return {'url': url, 'status': 'read', 'untrusted_text': 'x'}

        with patch('resident.fetch_public_text', side_effect=fake_fetch):
            resident_mod.gather_sources([{'text': text}], {'links': LINKS_CFG})
        return seen

    def test_chinese_after_link_is_not_swallowed(self):
        self.assertEqual(self.gather('看这个 https://a.example/b，挺好的'), ['https://a.example/b'])

    def test_link_inside_chinese_sentence(self):
        self.assertEqual(self.gather('你搜一下https://a.example/x 就知道'), ['https://a.example/x'])

    def test_ascii_trailing_punctuation_is_stripped(self):
        self.assertEqual(self.gather('see https://a.example/y.'), ['https://a.example/y'])

    def test_plain_text_has_no_url(self):
        self.assertEqual(self.gather('今天天气不错'), [])


class QQUrlExtractionTests(unittest.TestCase):
    def test_same_rule_on_qq_side(self):
        urls = qq_service.extract_urls([{'text': '看这个 https://a.example/b，挺好的'}])
        self.assertEqual(list(urls), ['https://a.example/b'])

    def test_ascii_trailing_punctuation(self):
        self.assertEqual(list(qq_service.extract_urls([{'text': 'https://a.example/y.'}])),
                         ['https://a.example/y'])


if __name__ == '__main__':
    unittest.main()
