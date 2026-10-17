"""模型接入层离线测试：provider 解析、请求形状、重试/熔断、认证失败、用量记录。

全程不打网络：urlopen 被替换成假响应；sleep 被替换掉，测试不真的等退避。
"""
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / 'src'))
import model_api                                                  # noqa: E402
from model_api import (ModelProvider, resolve_providers, ModelUnavailable,   # noqa: E402
                       ModelAuthError, ModelCircuitOpen)


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


def ok_body(text='你好', usage=None):
    return {'choices': [{'message': {'content': text}, 'finish_reason': 'stop'}],
            'usage': usage or {'prompt_tokens': 11, 'completion_tokens': 7, 'total_tokens': 18}}


def http_error(code, headers=None, body=b'err'):
    return urllib.error.HTTPError('http://x', code, 'boom', headers or {}, io.BytesIO(body))


GO_BLOCK = {
    'enabled': True,
    'base_url': 'https://opencode.ai/zen/go/v1',
    'model': 'mimo-v2.6-flash',
    'api_key_env': 'OPENCODE_API_KEY',
    'credential_file': 'credentials.json',
    'credential_key': 'opencode_api_key',
    'app_user_agent': 'niangao-wechat-agent/1.0',
    'session_header': 'x-opencode-session',
    'timeout': 5, 'max_retries': 2, 'breaker_after': 3, 'breaker_seconds': 60,
    'temperature': 0.1,
    'ocr': {'base_url': 'https://api.stepfun.com/step_plan/v1', 'model': 'step-3.7-flash',
            'credential_key': 'step_plan_api_key', 'timeout': 5},
}

LEGACY = {'step_plan': {'base_url': 'https://api.stepfun.com/step_plan/v1',
                        'model': 'step-5-preview', 'api_key_env': 'STEP_PLAN_API_KEY',
                        'credential_file': 'credentials.json', 'timeout': 5,
                        'reasoning_effort': 'low', 'ocr_model': 'step-3.7-flash'}}


def provider(block=None, creds=None, **kw):
    p = ModelProvider(block or GO_BLOCK, 'main', session_file=Path('/tmp/test-model-session'))
    if creds is not None:
        p._key_override = creds
    return p


class ProviderResolutionTests(unittest.TestCase):
    def test_legacy_config_keeps_stepfun_and_its_ocr_model(self):
        p = resolve_providers(LEGACY)
        self.assertEqual(p['main'].model, 'step-5-preview')
        self.assertEqual(p['main'].credential_key, 'step_plan_api_key')
        self.assertEqual(p['main'].reasoning_effort, 'low')
        self.assertEqual(p['ocr'].model, 'step-3.7-flash')
        self.assertIsNone(p['ocr'].reasoning_effort, 'OCR 不该带 reasoning_effort')

    def test_disabled_new_block_falls_back_to_legacy(self):
        cfg = dict(LEGACY)
        cfg['model'] = dict(GO_BLOCK, enabled=False)
        self.assertEqual(resolve_providers(cfg)['main'].model, 'step-5-preview')

    def test_enabled_new_block_switches_main_but_not_ocr(self):
        cfg = dict(LEGACY)
        cfg['model'] = dict(GO_BLOCK, enabled=True)
        p = resolve_providers(cfg)
        self.assertEqual(p['main'].model, 'mimo-v2.6-flash')
        self.assertEqual(p['main'].base_url, 'https://opencode.ai/zen/go/v1')
        self.assertEqual(p['ocr'].model, 'step-3.7-flash')
        self.assertIn('stepfun', p['ocr'].base_url)


class RequestShapeTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        def fake_urlopen(req, timeout=None):
            self.sent.append(req)
            return FakeResponse(ok_body())
        self._p = patch('urllib.request.urlopen', side_effect=fake_urlopen)
        self._p.start(); self.addCleanup(self._p.stop)
        self._s = patch('model_api.time.sleep'); self._s.start(); self.addCleanup(self._s.stop)
        env = patch.dict('os.environ', {'OPENCODE_API_KEY': 'test-key'})
        env.start(); self.addCleanup(env.stop)

    def test_headers_identify_app_and_session(self):
        p = provider()
        p.session_for('group:人机')
        p.chat([{'role': 'user', 'content': 'hi'}], 100)
        headers = {k.lower(): v for k, v in self.sent[0].headers.items()}
        self.assertEqual(headers.get('user-agent'), 'niangao-wechat-agent/1.0')
        session = headers.get('x-opencode-session')
        self.assertTrue(session and len(session) == 24)
        self.assertNotIn('人机', session, 'session 里不能有群名')
        self.assertEqual(headers.get('authorization'), 'Bearer test-key')

    def test_payload_has_model_and_no_reasoning_unless_configured(self):
        p = provider()
        p.chat([{'role': 'user', 'content': 'hi'}], 123)
        body = json.loads(self.sent[0].data.decode())
        self.assertEqual(body['model'], 'mimo-v2.6-flash')
        self.assertEqual(body['max_tokens'], 123)
        self.assertNotIn('reasoning_effort', body, '没显式配置就不该发这个参数')
        self.assertFalse(body['stream'])

    def test_reasoning_effort_only_when_explicit(self):
        block = dict(GO_BLOCK, reasoning_effort='low')
        with patch.dict('os.environ', {'OPENCODE_API_KEY': 'k'}):
            ModelProvider(block, 'main').chat([{'role': 'user', 'content': 'x'}], 9)
        self.assertEqual(json.loads(self.sent[0].data.decode())['reasoning_effort'], 'low')

    def test_usage_is_recorded(self):
        recs = []
        p = provider()
        p.recorder = recs.append
        p.chat([{'role': 'user', 'content': 'hi'}], 10)
        self.assertEqual(recs[0]['ok'], True)
        self.assertEqual(recs[0]['total_tokens'], 18)
        self.assertEqual(recs[0]['provider'], 'main')


class FailureHandlingTests(unittest.TestCase):
    def setUp(self):
        self._s = patch('model_api.time.sleep'); self._s.start(); self.addCleanup(self._s.stop)
        env = patch.dict('os.environ', {'OPENCODE_API_KEY': 'k'})
        env.start(); self.addCleanup(env.stop)

    def test_missing_key_is_unavailable_not_crash(self):
        with patch.dict('os.environ', {'OPENCODE_API_KEY': ''}):
            p = ModelProvider(GO_BLOCK, 'main')
            with patch.object(ModelProvider, 'key', return_value=''):
                with self.assertRaises(ModelUnavailable):
                    p.chat([{'role': 'user', 'content': 'x'}], 10)

    def test_401_disables_provider_and_does_not_retry(self):
        calls = []
        def fake(req, timeout=None):
            calls.append(req)
            raise http_error(401)
        with patch('urllib.request.urlopen', side_effect=fake):
            p = ModelProvider(GO_BLOCK, 'main')
            with self.assertRaises(ModelAuthError):
                p.chat([{'role': 'user', 'content': 'x'}], 10)
        self.assertEqual(len(calls), 1, '认证失败不该重试')
        self.assertTrue(p.disabled_reason)
        self.assertIn('认证', p.disabled_reason)
        # 停用后再调用：直接失败，不再打出去
        with patch('urllib.request.urlopen', side_effect=fake):
            with self.assertRaises(ModelAuthError):
                p.chat([{'role': 'user', 'content': 'x'}], 10)

    def test_429_honours_retry_after_then_succeeds(self):
        seq = [http_error(429, {'Retry-After': '3'}), FakeResponse(ok_body('好了'))]
        def fake(req, timeout=None):
            item = seq.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        with patch('urllib.request.urlopen', side_effect=fake):
            p = ModelProvider(GO_BLOCK, 'main')
            text, usage = p.chat([{'role': 'user', 'content': 'x'}], 10)
        self.assertEqual(text, '好了')
        self.assertEqual(usage['total_tokens'], 18)

    def test_5xx_retries_then_gives_up(self):
        calls = []
        def fake(req, timeout=None):
            calls.append(req)
            raise http_error(503)
        with patch('urllib.request.urlopen', side_effect=fake):
            p = ModelProvider(GO_BLOCK, 'main')
            with self.assertRaises(ModelUnavailable):
                p.chat([{'role': 'user', 'content': 'x'}], 10)
        self.assertEqual(len(calls), 3, 'max_retries=2 → 最多 3 次尝试')

    def test_breaker_opens_after_consecutive_failures(self):
        def fake(req, timeout=None):
            raise http_error(500)
        with patch('urllib.request.urlopen', side_effect=fake):
            p = ModelProvider(GO_BLOCK, 'main')
            for _ in range(2):
                with self.assertRaises(ModelUnavailable):
                    p.chat([{'role': 'user', 'content': 'x'}], 10)
            # 第 3 次失败后熔断（breaker_after=3 是在 provider 层计数）
            with self.assertRaises(ModelUnavailable):
                p.chat([{'role': 'user', 'content': 'x'}], 10)
            self.assertTrue(p.circuit_open(), '连续失败该熔断')
            with self.assertRaises(ModelCircuitOpen):
                p.chat([{'role': 'user', 'content': 'x'}], 10)

    def test_truncated_output_is_treated_as_failure_not_returned(self):
        body = {'choices': [{'message': {'content': '半句'}, 'finish_reason': 'length'}]}
        with patch('urllib.request.urlopen', return_value=FakeResponse(body)), \
             patch.object(model_api, 'ModelProvider', ModelProvider):
            p = ModelProvider(dict(GO_BLOCK, max_retries=0), 'main')
            with self.assertRaises(ModelUnavailable):
                p.chat([{'role': 'user', 'content': 'x'}], 10)


class StepPlanRoutingTests(unittest.TestCase):
    def test_stepplan_sends_ocr_to_ocr_provider(self):
        cfg = dict(LEGACY)
        cfg['model'] = dict(GO_BLOCK, enabled=True)
        import multimodal
        seen = {}

        class Spy:
            def __init__(self, name):
                self.name = name
            def chat(self, messages, max_tokens, model=None, session_id=None):
                seen[self.name] = model or 'provider-default'
                return ('文字', {})
            def key(self):
                return 'k'
            def session_for(self, chat_key=None):
                return ''
            def health(self):
                return {'name': self.name, 'model': 'm', 'base_url': 'b', 'key_present': True,
                        'disabled_reason': '', 'circuit_open': False, 'last_error': '',
                        'session_bound': False}

        plan = multimodal.StepPlan(cfg)
        plan.main = Spy('main')
        plan.ocr = Spy('ocr')
        plan.call([{'role': 'user', 'content': 'x'}], 10)
        plan.call([{'role': 'user', 'content': 'x'}], 10, provider='ocr')
        self.assertEqual(seen['main'], 'provider-default', '主模型用 provider 自带模型')
        self.assertEqual(seen['ocr'], 'provider-default', 'OCR 用 OCR provider 自带模型')


if __name__ == '__main__':
    unittest.main()
