"""_QuotedOCR 必须同时实现单气泡和**批量**两条路。

2026-10-17 实测事故：批量版本缺失 → AttributeError 被 ocr_bubbles 的 except 吞掉
→ 模型纠正 OCR 从来没跑过，群里读到的全是 tesseract 错字（@年糕 读成 @#ik），
机器人照着错字回话。这个测试就是钉死这两条路都在、都扣额度。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from resident import _QuotedOCR                                  # noqa: E402


class FakeModel:
    def __init__(self):
        self.calls = []

    def ocr_bubble_image(self, image):
        self.calls.append(('single', image))
        return '单个气泡'

    def ocr_bubbles_image(self, image, bboxes):
        self.calls.append(('batch', image, tuple(map(tuple, bboxes))))
        return {0: '批量气泡'}


class FakeResident:
    def __init__(self):
        self.spent = []

    def spend(self, model, cfg, priority, what):
        self.spent.append((priority, what))


class QuotedOCRTests(unittest.TestCase):
    def test_batch_method_exists_and_delegates(self):
        resident, model = FakeResident(), FakeModel()
        wrapper = _QuotedOCR(resident, {}, model)
        self.assertTrue(hasattr(wrapper, 'ocr_bubbles_image'),
                        '观察管道走的是批量 OCR，缺了它模型纠正会静默失效')
        out = wrapper.ocr_bubbles_image('img', [(0, 0, 10, 10)])
        self.assertEqual(out, {0: '批量气泡'})
        self.assertEqual(model.calls[0][0], 'batch')

    def test_single_method_still_works(self):
        resident, model = FakeResident(), FakeModel()
        wrapper = _QuotedOCR(resident, {}, model)
        self.assertEqual(wrapper.ocr_bubble_image('img'), '单个气泡')

    def test_both_paths_charge_quota(self):
        resident, model = FakeResident(), FakeModel()
        wrapper = _QuotedOCR(resident, {}, model)
        wrapper.ocr_bubble_image('img')
        wrapper.ocr_bubbles_image('img', [])
        self.assertEqual([w for _, w in resident.spent], ['ocr', 'ocr'])
        self.assertEqual(len(resident.spent), 2)


if __name__ == '__main__':
    unittest.main()
