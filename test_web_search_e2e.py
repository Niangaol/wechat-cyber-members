"""端到端接线测试：一条消息真的走完 process_queue，看"模型自己发起的搜索"有没有通。

和 test_web_search_tool（纯协议）的分工：这里连的是**真 Resident 的发送链路**——
队列 → spend → model.reply(search_fn=...) → 模型决定调工具 → 执行器真的打 Tavily → 回复发出。

为什么不用 test_integration.make_resident：它要在临时目录写 credentials.json。
这台开发机上跑测试的 python 有时没有写盘权限，所以这里把落盘全换成内存：
STATE 指向不存在的目录、atomic_json 换成记录器。
"""
import json, sqlite3, sys, time, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent/'src'))
sys.path.insert(0, str(Path(__file__).parent))          # 复用 test_integration 的假件

import resident as resident_mod
from quota import Quota, PRIORITY_GROUP_AT
from memory import ChatMemory
from search import HotFeed
from moment_interact import MomentInbox
from resident import Resident
from web_search import WebSearch
from test_integration import FakeWeChatUI, FakeModel, FakeNavigator, FakeConfig

GROUP = '测试群'
CK = 'group:' + GROUP
# Tavily 的真实结果形状（score 是 0~1，正文在 content）
SAFE_RESULTS = [
    {'title': '手柄横评', 'url': 'https://example.com/a',
     'content': '摇杆手感对比。', 'score': 0.8, 'id': '1'},
]

CFG = {
    'target_chat': '很帅的年糕', 'watch_chats': [GROUP], 'group_whitelist': [GROUP],
    'chat_types': {GROUP: 'group'}, 'direct_enabled': True,
    'display': ':99', 'poll_seconds': 1, 'debounce_seconds': 0, 'reply_max_chars': 200,
    'min_reply_seconds': 0, 'max_replies_per_hour': 30, 'max_send_retries': 2,
    'expected_width': 980, 'expected_height': 710,
    'limits': {'window_5h': 500, 'window_1d': 5000},
    'remind_cooldown': 300,
    'automation': {'enabled': True},
    'groups': {GROUP: {'plain_mode': 'all'}},
    'links': {'enabled': False},
    'image_reply': {'enabled': False},
    'moments': {'enabled': False},
    'interact': {'enabled': False},
    'mention_aliases': ['年糕'],
    'web_search': {'enabled': True, 'provider': 'tavily', 'min_score': 0.3,
                   'cache_ttl': 600},
}


class ToolCallingModel(FakeModel):
    """模拟真实模型：第一轮要求调搜索工具，拿到结果后再出正文。"""

    def __init__(self, query='国产手柄', call_times=1, reply_text='查到了：京东有排行榜'):
        super().__init__(reply_text)
        self.query = query
        self.call_times = call_times
        self.search_results = None
        self.search_calls = 0

    def reply(self, new_messages, history, web_sources, chat_context=None, hot_items=None,
              search_fn=None):
        self.calls.append('reply')
        self.hot_items = hot_items
        self.search_fn = search_fn
        for _ in range(self.call_times):
            if search_fn is None:
                break
            self.search_calls += 1
            self.search_results = search_fn(self.query)
        return self.reply_text


def make_resident():
    """手工装配一个不落盘的 Resident（属性集与 test_integration.make_resident 对齐）。"""
    r = Resident.__new__(Resident)
    r.db = sqlite3.connect(':memory:')
    r.db.execute('CREATE TABLE IF NOT EXISTS deliveries('
                 ' id INTEGER PRIMARY KEY, created REAL, state TEXT, digest TEXT)')
    r.quota = Quota(r.db)
    r.memory = ChatMemory(r.db)
    r.feed = HotFeed(r.db)
    r.inbox = MomentInbox(r.db)
    r.baselines, r.last_hash, r.last_sent, r.last_remind = {}, {}, {}, {}
    r.last_frame, r.seen_signatures, r.chat_failures, r.history = {}, {}, {}, {}
    r.running, r.failures = True, 0
    r.moments = r.interact = r.nav = r.release = None
    r.image_sent = {}
    r.stop = Path('definitely-not-a-stop-file')     # .exists() 必须为 False
    return r


class QueueWiringTests(unittest.TestCase):
    def setUp(self):
        self.statuses = []
        self.atomic = patch.object(resident_mod, 'atomic_json',
                                   lambda path, value: self.statuses.append(value))
        self.atomic.start()
        self.addCleanup(self.atomic.stop)
        state = patch.object(resident_mod, 'STATE', Path('definitely-not-a-state-dir'))
        state.start()
        self.addCleanup(state.stop)
        self.key = patch.object(WebSearch, 'key', lambda self: 'test-key')
        self.key.start()
        self.addCleanup(self.key.stop)
        self.r = make_resident()
        self.addCleanup(self.r.db.close)
        self.ui = FakeWeChatUI()
        self.r.nav = FakeNavigator(self.ui)

    def post(self, handler):
        patcher = patch.object(WebSearch, '_post', handler)
        patcher.start()
        self.addCleanup(patcher.stop)

    def enqueue(self, text, want_search=False):
        payload = json.dumps({'messages': [{'direction': 'in', 'kind': 'text',
                                            'text': text, 'at_me': True,
                                            'signature': 'sig-1'}],
                              'want_search': want_search}, ensure_ascii=False)
        self.r.quota.enqueue(CK, PRIORITY_GROUP_AT, payload)

    def run_queue(self, model):
        with patch('resident.CONFIG', FakeConfig(CFG)):
            self.r.process_queue(CFG, self.ui, model)
        return model

    def submitted(self):
        return [s for s in self.statuses if s.get('state') == 'reply_submitted']

    # ---------- 主路径 ----------
    def test_model_driven_search_hits_the_api_and_is_reported(self):
        posts = []

        def handler(ws, path, body):
            posts.append((path, body))
            return {'results': SAFE_RESULTS}
        self.post(handler)
        self.enqueue('最新手柄哪款好')
        model = self.run_queue(ToolCallingModel(query='国产手柄'))
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0][0], '/search')             # Tavily 的路径
        self.assertEqual(posts[0][1]['query'], '国产手柄')    # 用的是**模型给的**查询词
        self.assertEqual([i['title'] for i in model.search_results], ['手柄横评'])
        submitted = self.submitted()
        self.assertTrue(submitted)
        self.assertEqual(submitted[-1]['search_calls'], 1)
        self.assertEqual(submitted[-1]['search_hits'], 1)

    def test_no_tool_call_means_no_network_at_all(self):
        self.post(lambda ws, path, body: self.fail('模型没调工具就不该联网'))
        self.enqueue('吃了吗')
        model = self.run_queue(ToolCallingModel(call_times=0))
        self.assertEqual(model.search_calls, 0)
        self.assertEqual([s for s in self.statuses if s.get('state') == 'reply_submitted'][-1]
                         ['search_calls'], 0)

    def test_model_cannot_search_twice_in_one_reply(self):
        posts = []

        def handler(ws, path, body):
            posts.append(body)
            return {'results': SAFE_RESULTS}
        self.post(handler)
        self.enqueue('最新手柄哪款好')
        model = self.run_queue(ToolCallingModel(call_times=2))     # 想调两次
        self.assertEqual(len(posts), 1)                            # 只放行一次
        self.assertEqual(len(model.search_results), 0)             # 第二次空手而归
        self.assertEqual(self.submitted()[-1]['search_calls'], 1)

    def test_search_failure_does_not_block_the_reply(self):
        import urllib.error

        def boom(ws, path, body):
            raise urllib.error.HTTPError('https://x', 402, 'pay', {}, None)
        self.post(boom)
        self.enqueue('最新手柄哪款好')
        model = self.run_queue(ToolCallingModel())
        self.assertEqual(model.search_results, [])
        sent = [t for t in self.ui.sent_texts if isinstance(t, tuple)]
        self.assertTrue(sent, '搜索失败不该阻止回复')

    def test_search_disabled_still_replies(self):
        cfg = {k: v for k, v in CFG.items()}
        cfg['web_search'] = {'enabled': False, 'provider': 'tavily'}
        self.post(lambda ws, path, body: self.fail('关掉搜索后不该联网'))
        self.enqueue('最新手柄哪款好')
        model = ToolCallingModel()
        with patch('resident.CONFIG', FakeConfig(cfg)):
            self.r.process_queue(cfg, self.ui, model)
        self.assertEqual(model.search_results, [])
        self.assertTrue([t for t in self.ui.sent_texts if isinstance(t, tuple)])


if __name__ == '__main__':
    unittest.main()
