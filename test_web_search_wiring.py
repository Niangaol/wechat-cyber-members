"""接线测试：搜索执行器怎么接进 Resident、怎么接进回复。

纯内存：不写盘、不打网络。resident 在 Windows 上要靠 fcntl 桩才能导入，
Linux/WSL 里直接跑即可。
"""
import inspect, sqlite3, sys, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).parent/'src'))

import resident as resident_mod
from multimodal import StepPlan
from web_search import WebSearch

# Tavily 的真实结果形状（score 是 0~1，正文在 content）
SAFE_RESULTS = [
    {'title': '手柄横评', 'url': 'https://example.com/a',
     'content': '摇杆手感对比。', 'score': 0.8, 'id': '1'},
]
CFG = {'web_search': {'enabled': True, 'provider': 'tavily', 'min_score': 0.3},
       'mention_aliases': ['年糕']}


class FakeResident:
    """只带 search_tool 需要的两样东西：db 和 status。"""

    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.events = []

    def status(self, state, **kw):
        self.events.append((state, kw))


def make_tool(fake, cfg=None):
    calls = []
    return resident_mod.Resident.search_tool(fake, cfg or CFG, calls), calls


class SearchToolTests(unittest.TestCase):
    def setUp(self):
        self.key = mock.patch.object(WebSearch, 'key', lambda self: 'test-key')
        self.key.start()
        self.addCleanup(self.key.stop)
        self.fake = FakeResident()

    def post(self, handler):
        patcher = mock.patch.object(WebSearch, '_post', handler)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_disabled_block_returns_nothing_and_never_calls_out(self):
        run, _calls = make_tool(self.fake, {'web_search': {'enabled': False}})
        self.post(lambda *a, **k: self.fail('禁用时不该发请求'))
        self.assertEqual(run('最新手柄'), [])

    def test_results_flow_back_and_status_is_recorded(self):
        self.post(lambda ws, path, body: {'results': SAFE_RESULTS})
        run, calls = make_tool(self.fake)
        items = run('最新手柄')
        self.assertEqual([i['title'] for i in items], ['手柄横评'])
        self.assertEqual(calls, [1])                    # 记录"调过一次、拿到 1 条"
        self.assertTrue(any(s == 'web_searched' for s, _ in self.fake.events))

    def test_alias_is_stripped_from_the_model_supplied_query(self):
        seen = {}
        self.post(lambda ws, path, body: seen.update(body) or {'results': SAFE_RESULTS})
        run, _calls = make_tool(self.fake)
        run('年糕 最新手柄哪个好')
        self.assertEqual(seen['query'], '最新手柄哪个好')

    def test_executor_allows_only_one_call_per_reply(self):
        """模型的第二段没有工具入口，这里是执行器自己的第二道闸。"""
        hits = []
        self.post(lambda ws, path, body: hits.append(1) or {'results': SAFE_RESULTS})
        run, calls = make_tool(self.fake)
        self.assertTrue(run('第一次'))
        self.assertEqual(run('第二次'), [])              # 第二次空手而归
        self.assertEqual(len(hits), 1)                  # 而且没有真的再查一次
        self.assertEqual(len(calls), 1)

    def test_failed_search_is_counted_so_it_cannot_retry(self):
        import urllib.error

        def boom(ws, path, body):
            raise urllib.error.HTTPError('https://x', 402, 'pay', {}, None)
        self.post(boom)
        run, calls = make_tool(self.fake)
        self.assertEqual(run('最新手柄'), [])
        self.assertEqual(len(calls), 1)                 # 失败也算查过了
        self.assertEqual(run('换个词再来'), [])

    def test_blank_query_is_not_counted(self):
        run, calls = make_tool(self.fake)
        self.assertEqual(run('   '), [])
        self.assertEqual(calls, [])                     # 空查询不算一次调用

    def test_exception_inside_search_is_swallowed(self):
        run, _calls = make_tool(self.fake)
        with mock.patch.object(WebSearch, 'search', side_effect=RuntimeError('炸了')):
            self.assertEqual(run('最新手柄'), [])
        self.assertTrue(any(s == 'web_search_failed' for s, _ in self.fake.events))


class SourceWiringTests(unittest.TestCase):
    """静态守卫：resident 那条调用链上的关键字参数被误删时立刻失败。"""

    def test_resident_hands_the_tool_to_reply(self):
        source = (Path(__file__).parent/'src'/'resident.py').read_text(encoding='utf-8')
        self.assertIn('search_fn=search_fn', source)
        self.assertIn('self.search_tool(', source)

    def test_reply_signature_uses_search_fn(self):
        params = inspect.signature(StepPlan.reply).parameters
        self.assertIn('search_fn', params)
        self.assertNotIn('search_items', params)        # 预取那条路已经撤掉


if __name__ == '__main__':
    unittest.main()
