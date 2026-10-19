"""OCR 预算与失败分类的回归测试。

2026-10-19 实测事故，两条都藏在"看起来正常"的路径里：
1) 批量 OCR 的 max_tokens 只有 600。step-3.7-flash 是推理模型，思考+正文一起
   挤占这 600，整屏气泡的中文原文经常写不完 → finish_reason=length → 被记成
   笼统的 'parse' → visual_parse 静默退回本机 tesseract，群里读到的全是错字
   （@年糕 读成 @#ik 那类），而且查账时只看 'parse' 看不出是截断。
2) step_plan.model 和 ocr_model 同名时 resolve_providers 走 ocr = main，于是
   OCR 请求带上主对话的 reasoning_effort（预算被进一步吃光），还和主回复共用
   一个熔断器：OCR 连挂 3 次会把主回复一起挡 60 秒。旧测试的 LEGACY 两个模型
   不同，刚好绕过这条路径，所以线上踩了坑测试全绿。

这两个测试类就是钉死：预算给够、死因能分类、OCR 与主链路互相不拖累。
"""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / 'src'))
import model_api                                                   # noqa: E402
from model_api import ModelProvider, ModelUnavailable, resolve_providers   # noqa: E402
import multimodal                                                  # noqa: E402
from PIL import Image                                              # noqa: E402

# 线上真实形态：主模型和 ocr_model 同名（都是 step-3.7-flash），主对话带 low 推理档位
SAME_MODEL_LEGACY = {'step_plan': {
    'base_url': 'https://api.stepfun.com/step_plan/v1',
    'model': 'step-3.7-flash',
    'api_key_env': 'STEP_PLAN_API_KEY',
    'credential_file': 'credentials.json',
    'timeout': 5, 'reasoning_effort': 'low', 'ocr_model': 'step-3.7-flash'}}


class FakeResponse:
    def __init__(self, payload, status=200):
        self._body = json.dumps(payload).encode()
        self.status = status
    def read(self, n=None):
        return self._body
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class RawResponse:
    """不是 JSON 的响应体（HTML 错误页那种）。"""
    status = 200
    def read(self, n=None):
        return b'<html>502 Bad Gateway</html>'
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def trunc_body():
    """finish_reason=length，但 usage 是有的——真实端点就是这样，以前被白扔了。"""
    return {'choices': [{'message': {'content': '前半句'}, 'finish_reason': 'length'}],
            'usage': {'prompt_tokens': 608, 'completion_tokens': 600,
                       'total_tokens': 1208}}


class SameModelOcrProviderTests(unittest.TestCase):
    """ocr_model 和主模型同名：也必须分开，不能图省事 ocr = main。"""

    def test_ocr_is_a_separate_provider(self):
        p = resolve_providers(SAME_MODEL_LEGACY)
        self.assertIsNot(p['ocr'], p['main'], '同名也要分开，否则共用一个熔断器')
        self.assertEqual(p['ocr'].name, 'ocr')
        self.assertEqual(p['ocr'].model, 'step-3.7-flash')

    def test_ocr_request_drops_reasoning_effort(self):
        sent = []

        def fake_urlopen(req, timeout=None):
            sent.append(json.loads(req.data.decode()))
            return FakeResponse({'choices': [{'message': {'content': '字'}}],
                                 'usage': {'prompt_tokens': 1, 'completion_tokens': 1,
                                           'total_tokens': 2}})

        with patch('urllib.request.urlopen', side_effect=fake_urlopen), \
             patch.dict('os.environ', {'STEP_PLAN_API_KEY': 'k'}):
            p = resolve_providers(SAME_MODEL_LEGACY)
            p['ocr'].chat([{'role': 'user', 'content': 'x'}], 600)
            p['main'].chat([{'role': 'user', 'content': 'x'}], 600)
        self.assertNotIn('reasoning_effort', sent[0],
                         'OCR 不该带推理档位：思考会吃光那点预算')
        self.assertEqual(sent[1].get('reasoning_effort'), 'low', '主对话照旧带')

    def test_ocr_failures_do_not_open_main_breaker(self):
        def boom(req, timeout=None):
            raise model_api.urllib.error.HTTPError('http://x', 500, 'boom', {},
                                                   io.BytesIO(b'e'))

        with patch('urllib.request.urlopen', side_effect=boom), \
             patch('model_api.time.sleep'), \
             patch.dict('os.environ', {'STEP_PLAN_API_KEY': 'k'}):
            p = resolve_providers(SAME_MODEL_LEGACY)
            for _ in range(4):
                with self.assertRaises(ModelUnavailable):
                    p['ocr'].chat([{'role': 'user', 'content': 'x'}], 600)
            self.assertTrue(p['ocr'].circuit_open(), 'OCR 自己该熔断')
            self.assertFalse(p['main'].circuit_open(),
                             'OCR 挂掉不该把主回复一起挡 60 秒')


class ErrorClassificationTests(unittest.TestCase):
    """'parse' 一个词曾把三种死因混在一起，害我排查时判错方向。现在分开落账。"""

    def _run_with(self, response):
        recs = []
        with patch('urllib.request.urlopen', return_value=response), \
             patch('model_api.time.sleep'), \
             patch.dict('os.environ', {'STEP_PLAN_API_KEY': 'k'}):
            p = ModelProvider(dict(SAME_MODEL_LEGACY['step_plan'], max_retries=0), 'main')
            p.recorder = recs.append
            with self.assertRaises(ModelUnavailable):
                p.chat([{'role': 'user', 'content': 'x'}], 600)
        return recs[0]

    def test_truncated_is_its_own_reason_and_keeps_usage(self):
        rec = self._run_with(FakeResponse(trunc_body()))
        self.assertEqual(rec['error'], 'truncated')
        self.assertEqual(rec['total_tokens'], 1208, '失败也要记真实用量，账本才不少算')

    def test_empty_body_is_its_own_reason(self):
        body = {'choices': [{'message': {'content': '   '}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 9, 'completion_tokens': 3, 'total_tokens': 12}}
        rec = self._run_with(FakeResponse(body))
        self.assertEqual(rec['error'], 'empty_body')
        self.assertEqual(rec['total_tokens'], 12)

    def test_not_json_is_its_own_reason(self):
        rec = self._run_with(RawResponse())
        self.assertEqual(rec['error'], 'not_json')

    def test_model_parse_error_carries_reason_and_usage(self):
        exc = model_api.ModelParseError('x', reason='truncated',
                                        usage={'total_tokens': 5})
        self.assertIsInstance(exc, ValueError, '必须还是 ValueError，老调用方靠它兜底')
        self.assertEqual(exc.reason, 'truncated')
        self.assertEqual(exc.usage['total_tokens'], 5)


class OcrBudgetTests(unittest.TestCase):
    """预算必须够写完一整屏气泡的中文原文，否则就是静默退回 tesseract。"""

    def _budget(self, method, *args):
        seen = {}

        class Spy:
            def chat(self, messages, max_tokens, model=None, session_id=None):
                seen['max_tokens'] = max_tokens
                return ('{}', {})
            def key(self):
                return 'k'
            def session_for(self, chat_key=None):
                return ''

        plan = multimodal.StepPlan({'step_plan': dict(SAME_MODEL_LEGACY['step_plan'])})
        plan.main = Spy()
        plan.ocr = Spy()
        getattr(plan, method)(*args)
        return seen['max_tokens']

    def test_batch_budget_covers_a_full_screen(self):
        img = Image.new('RGB', (707, 560), 'white')
        n = self._budget('ocr_bubbles_image', img,
                         [(10, 10, 200, 60), (10, 80, 200, 130)])
        self.assertGreaterEqual(n, 2000,
                                '整屏气泡批量读：600 实测被思考+正文挤爆，6/12 次失败')

    def test_single_bubble_budget_covers_one_bubble(self):
        img = Image.new('RGB', (400, 80), 'white')
        n = self._budget('ocr_bubble_image', img)
        self.assertGreaterEqual(n, 600, '单个气泡中文原文实测就要 300-570 token')


if __name__ == '__main__':
    unittest.main()
