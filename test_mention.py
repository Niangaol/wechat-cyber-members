import unittest
from visual_parse import mentions_me, has_at_mention
from PIL import Image, ImageDraw

class MentionTests(unittest.TestCase):
    ALIASES = ['年糕Agent', '年糕']
    def test_direct_mention_with_space(self):
        self.assertTrue(mentions_me('@年糕 Agent 我自我介绍一下', self.ALIASES))
    def test_mention_without_space(self):
        self.assertTrue(mentions_me('@年糕Agent 在吗', self.ALIASES))
    def test_mention_broken_by_ocr_spacing(self):
        self.assertTrue(mentions_me('@ 年 糕 Agent 自我介绍一下', self.ALIASES))
    def test_mention_tolerates_ocr_typo(self):
        """实测 OCR 把 '@年糕 Agent 在吗' 读成 '@@年糙 Agent 在吗'，仍要算在叫我。"""
        self.assertTrue(mentions_me('@@年糙 Agent 在吗', self.ALIASES))
        self.assertTrue(mentions_me('@年高Agent 你好', self.ALIASES))

    def test_other_person_not_matched(self):
        self.assertFalse(mentions_me('@Deepseek 神了', self.ALIASES))
    def test_no_at_sign_not_matched(self):
        self.assertFalse(mentions_me('年糕Agent真可爱', self.ALIASES))
    def test_empty_alias_ignored(self):
        self.assertFalse(mentions_me('@年糕 在吗', ['']))
    def test_blue_highlight_still_detected(self):
        img = Image.new('RGB', (300, 100), (255, 255, 255))
        ImageDraw.Draw(img).text((20, 40), '@我', fill=(70, 130, 255))
        self.assertTrue(has_at_mention(img, (0, 0, 300, 100)))
    def test_plain_black_text_is_not_blue_mention(self):
        img = Image.new('RGB', (300, 100), (255, 255, 255))
        ImageDraw.Draw(img).text((20, 40), '普通消息', fill=(22, 22, 22))
        self.assertFalse(has_at_mention(img, (0, 0, 300, 100)))

if __name__ == '__main__':
    unittest.main()
