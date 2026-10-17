import sys, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).parent/'src'))
from visual_parse import (ocr_bubble, ocr_bubbles, needs_model_ocr, mentions_me,
                            _local_best, _cjk_count, extract_messages)


class FakeUI:
    """按预处理变体返回预定结果，用来锁定多变体择优逻辑。"""
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0
    def run(self, args, data=None, timeout=25):
        self.calls += 1
        return self.texts[min(self.calls - 1, len(self.texts) - 1)].encode('utf-8')


def bubble(with_text=True, height=80, stacked=False):
    img = Image.new('RGB', (200, height), (255, 255, 255))
    if with_text:
        rows = STACKED if stacked else [(0, 0, 200, 80)]
        for x1, y1, x2, y2 in rows:
            ImageDraw.Draw(img).text((x1+20, y1+30), '测试文字', fill=(22, 22, 22))
    return img


STACKED = [(0, 0, 200, 80), (0, 90, 200, 170), (0, 180, 200, 260)]


class LocalBestTests(unittest.TestCase):
    def test_picks_variant_with_most_chinese(self):
        ui = FakeUI(['ASAE 3', '怎么回事', 'GAS', 'ASAE 3'])
        self.assertEqual(_local_best(ui, bubble(), (0, 0, 200, 80)), '怎么回事')
        self.assertEqual(ui.calls, 4)
    def test_all_garbage_falls_back_to_longest(self):
        ui = FakeUI(['abc', 'ab', 'abcd', 'abc'])
        self.assertEqual(_local_best(ui, bubble(), (0, 0, 200, 80)), 'abcd')


class MentionTests(unittest.TestCase):
    ALIASES = ['年糕Agent', '年糕']
    def test_alias_variants(self):
        for text in ['@年糕 Agent 在吗', '@年糕Agent在吗', '@ 年 糕 Agent 在吗']:
            self.assertTrue(mentions_me(text, self.ALIASES), text)
    def test_non_mentions(self):
        for text in ['@Deepseek 神了', '年糕Agent真可爱', '', None]:
            self.assertFalse(mentions_me(text, self.ALIASES), text)


class NeedsModelTests(unittest.TestCase):
    ALIASES = ['年糕Agent', '年糕']
    def test_already_mentions_me_needs_no_model(self):
        self.assertFalse(needs_model_ocr('@年糕 Agent 在吗', bubble(), (0, 0, 200, 80), self.ALIASES))
    def test_at_sign_without_alias_needs_model(self):
        self.assertTrue(needs_model_ocr('@## Agent 在下', bubble(), (0, 0, 200, 80), self.ALIASES))
    def test_no_chinese_but_ink_needs_model(self):
        self.assertTrue(needs_model_ocr('ASAE 3', bubble(), (0, 0, 200, 80), self.ALIASES))
    def test_blank_bubble_needs_no_model(self):
        self.assertFalse(needs_model_ocr('', bubble(False), (0, 0, 200, 80), self.ALIASES))


class HybridTests(unittest.TestCase):
    ALIASES = ['年糕Agent', '年糕']
    def test_model_not_called_when_local_is_fine(self):
        ui = FakeUI(['神了', '神了', '神了', '神了'])
        model = unittest.mock.Mock()
        self.assertEqual(ocr_bubble(ui, bubble(), (0, 0, 200, 80), model=model, aliases=self.ALIASES), '神了')
        model.ocr_bubble_image.assert_not_called()
    def test_model_called_when_local_has_at_but_no_alias(self):
        ui = FakeUI(['@## Agent 在下', '@## Agent 在下', '@## Agent 在下', '@## Agent 在下'])
        model = unittest.mock.Mock()
        model.ocr_bubble_image.return_value = '@年糕 Agent 我自我介绍一下'
        text = ocr_bubble(ui, bubble(), (0, 0, 200, 80), model=model, aliases=self.ALIASES)
        self.assertEqual(text, '@年糕 Agent 我自我介绍一下')
        model.ocr_bubble_image.assert_called_once()
        self.assertTrue(mentions_me(text, self.ALIASES))
    def test_model_failure_keeps_local_result(self):
        ui = FakeUI(['ASAE 3', 'ASAE 3', 'ASAE 3', 'ASAE 3'])
        model = unittest.mock.Mock()
        model.ocr_bubble_image.side_effect = RuntimeError('boom')
        self.assertEqual(ocr_bubble(ui, bubble(), (0, 0, 200, 80), model=model, aliases=self.ALIASES), 'ASAE 3')
    def test_model_empty_result_keeps_local(self):
        ui = FakeUI(['ASAE 3', 'ASAE 3', 'ASAE 3', 'ASAE 3'])
        model = unittest.mock.Mock()
        model.ocr_bubble_image.return_value = '   '
        self.assertEqual(ocr_bubble(ui, bubble(), (0, 0, 200, 80), model=model, aliases=self.ALIASES), 'ASAE 3')
    def test_batch_uses_single_model_call_for_all_bubbles(self):
        # 3 个气泡 × 4 个预处理变体 = 12 次调用；第 2 个气泡全变体都读坏才触发批量
        ui = FakeUI(['神了']*4 + ['ASAE 3']*4 + ['神了']*4)
        model = unittest.mock.Mock()
        model.ocr_bubbles_image.return_value = {0: '神了', 1: '怎么回事', 2: '你 tm 是谁？'}
        out = ocr_bubbles(ui, bubble(height=300, stacked=True), STACKED, model=model, aliases=self.ALIASES)
        model.ocr_bubbles_image.assert_called_once()
        self.assertEqual(out, ['神了', '怎么回事', '你 tm 是谁？'])
    def test_batch_failure_keeps_all_local_results(self):
        ui = FakeUI(['ASAE 3']*4)
        model = unittest.mock.Mock()
        model.ocr_bubbles_image.side_effect = RuntimeError('boom')
        out = ocr_bubbles(ui, bubble(), [(0, 0, 200, 80)], model=model, aliases=self.ALIASES)
        self.assertEqual(out, ['ASAE 3'])
    def test_batch_partial_result_fills_from_local(self):
        ui = FakeUI(['ASAE 3']*4)
        model = unittest.mock.Mock()
        model.ocr_bubbles_image.return_value = {0: '怎么回事'}
        out = ocr_bubbles(ui, bubble(height=300, stacked=True), STACKED[:2], model=model, aliases=self.ALIASES)
        self.assertEqual(out, ['怎么回事', 'ASAE 3'])
    def test_batch_skipped_when_all_local_fine(self):
        ui = FakeUI(['神了']*4)
        model = unittest.mock.Mock()
        ocr_bubbles(ui, bubble(), [(0, 0, 200, 80)], model=model, aliases=self.ALIASES)
        model.ocr_bubbles_image.assert_not_called()
    def test_no_model_never_touches_network(self):
        ui = FakeUI(['神了', '神了', '神了', '神了'])
        import urllib.request
        with patch.object(urllib.request, 'urlopen', side_effect=AssertionError('no network')):
            self.assertEqual(ocr_bubble(ui, bubble(), (0, 0, 200, 80)), '神了')


    def test_batch_forced_past_heuristic_when_local_looks_confident(self):
        # 回归：本地读出含 CJK 的乱码（让 6 引号那种）会骗过 needs_model_ocr 的
        # 零 CJK 才触发判据，被判成可靠读数 -> 模型不被调用、错字原样入队。
        # force=True 表示调用方已确认值得花这一次，必须真的调用。
        ui = FakeUI(['让 6"'] * 4)
        model = unittest.mock.Mock()
        model.ocr_bubbles_image.return_value = {0: '你 tm 是谁？'}
        out = ocr_bubbles(ui, bubble(), [(0, 0, 200, 80)], model=model,
                          aliases=self.ALIASES, force=True)
        model.ocr_bubbles_image.assert_called_once()
        self.assertEqual(out, ['你 tm 是谁？'])
    def test_batch_not_forced_by_default(self):
        # 不传 force 时保持原语义：本地都读得好就一次都不调模型
        ui = FakeUI(['神了'] * 4)
        model = unittest.mock.Mock()
        ocr_bubbles(ui, bubble(), [(0, 0, 200, 80)], model=model, aliases=self.ALIASES)
        model.ocr_bubbles_image.assert_not_called()


if __name__ == '__main__':
    unittest.main()
