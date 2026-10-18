"""联网搜索的离线测试：不打网络，全部 mock（有 key 的机器上也照样能跑）。

两个 provider 的返回结构不一样，所以测试也分两组：
- TavilyTests / 默认路径：score 是 0~1，正文在 content
- DeepSeekProviderTests：rerank_score 是 0~3，有 summary/snippet 两层摘要
量纲混用是这里最容易出的错，所以两组都把"分数门槛"单独钉了一遍。
"""
import json, os, sqlite3, sys, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent/'src'))
import web_search
from web_search import WebSearch, build_query, cfg_of

# Tavily 真实返回结构（2026-10-18 实测：title/url/content/score/id/raw_content）
TAVILY_RAW = [
    {'title': '新款游戏手柄横评', 'url': 'https://www.example.com/a',
     'content': '三款国产手柄的手感对比', 'score': 0.82, 'id': '1', 'raw_content': None},
    {'title': '低分结果', 'url': 'https://example.com/low',
     'content': '相关性很差的页面', 'score': 0.11, 'id': '2'},
    {'title': '某地发生地震', 'url': 'https://example.com/bad',
     'content': '灾难报道', 'score': 0.9, 'id': '3'},
    {'title': '能用的结果', 'url': 'https://example.com/c',
     'content': '正常正文', 'score': 0.7, 'id': '4'},
    {'title': '坏链接', 'url': 'javascript:alert(1)',
     'content': '不是 http 链接', 'score': 0.5, 'id': '5'},
    'not-a-dict',
]

# DeepSeek 真实返回结构（rerank_score 0~3，两层摘要）
DEEPSEEK_RAW = [
    {'rerank_score': 2.4, 'title': '新款游戏手柄横评', 'url': 'https://example.com/a',
     'snippet': '三款国产手柄的手感对比', 'summary': '详细对比了摇杆与震动表现。',
     'site_name': 'Example', 'date': '2026-10-01T00:00:00+00:00', 'content': ''},
    {'rerank_score': 0.4, 'title': '低分结果', 'url': 'https://example.com/low',
     'snippet': '相关性很差的页面', 'summary': '无关', 'site_name': 'X', 'date': None},
    {'rerank_score': 2.0, 'title': '某地发生地震', 'url': 'https://example.com/bad',
     'snippet': '灾难报道', 'summary': '灾难细节', 'site_name': 'Y', 'date': None},
    {'rerank_score': 2.0, 'title': '能用的结果', 'url': 'https://example.com/c',
     'snippet': '短摘要', 'summary': '涉及政治话题的长摘要', 'site_name': 'Z', 'date': None},
]


def make(block=None, key='test-key'):
    ws = WebSearch(sqlite3.connect(':memory:'), block)
    ws.key = lambda: key            # 不碰真实凭据文件
    return ws


def tavily(block=None, key='test-key'):
    return make(dict({'provider': 'tavily'}, **(block or {})), key)


def deepseek(block=None, key='test-key'):
    return make(dict({'provider': 'deepseek'}, **(block or {})), key)


class BuildQueryTests(unittest.TestCase):
    def test_strips_alias_and_at_mentions(self):
        self.assertEqual(build_query('年糕 最新的手柄哪个好 @年糕Agent', ['年糕Agent', '年糕']),
                         '最新的手柄哪个好')

    def test_collapses_whitespace_and_truncates(self):
        q = build_query('a\n\n  b   c', [], max_chars=4)
        self.assertEqual(q, 'a b '[:4])

    def test_empty_input(self):
        self.assertEqual(build_query(None), '')
        self.assertEqual(build_query('   '), '')


class ConfigTests(unittest.TestCase):
    def test_ignores_comment_keys_and_keeps_defaults(self):
        cfg = cfg_of({'_说明': '给人看的', 'count': 3})
        self.assertNotIn('_说明', cfg)
        self.assertEqual(cfg['count'], 3)
        self.assertEqual(cfg['timeout'], web_search.DEFAULTS['timeout'])

    def test_default_provider_is_tavily(self):
        self.assertEqual(cfg_of({})['provider'], 'tavily')
        self.assertEqual(cfg_of({})['base_url'], 'https://api.tavily.com')

    def test_score_threshold_travels_with_provider(self):
        """分数门槛必须跟着 provider 走：0~1 和 0~3 混用会要么全丢要么全留。"""
        self.assertEqual(cfg_of({'provider': 'tavily'})['min_score'], 0.3)
        self.assertEqual(cfg_of({'provider': 'deepseek'})['min_score'], 1.2)

    def test_provider_block_overrides_toplevel(self):
        cfg = cfg_of({'provider': 'tavily', 'count': 9, 'tavily': {'count': 3}})
        self.assertEqual(cfg['count'], 3)          # 专属子块意图最强

    def test_unknown_provider_falls_back_and_records_it(self):
        cfg = cfg_of({'provider': 'tavli'})        # 拼错
        self.assertEqual(cfg['provider'], 'tavily')
        self.assertEqual(cfg['provider_fallback_from'], 'tavli')
        self.assertEqual(cfg['base_url'], 'https://api.tavily.com')


class TavilyTests(unittest.TestCase):
    """默认 provider：请求形状、结果解析、缓存/上限/熔断。"""

    def test_no_key_returns_empty_and_records_reason(self):
        ws = tavily(key='')
        self.assertEqual(ws.search('最新手柄'), [])
        self.assertIn('key', ws.last_error.lower())
        self.assertFalse(ws.ready())

    def test_disabled_returns_empty(self):
        ws = tavily({'enabled': False})
        ws._post = lambda *a, **k: self.fail('禁用时不该发请求')
        self.assertEqual(ws.search('最新手柄'), [])

    def test_filters_score_unsafe_and_bad_urls(self):
        ws = tavily()
        ws._post = lambda path, body: {'results': TAVILY_RAW}
        items = ws.search('手柄推荐')
        self.assertEqual([i['title'] for i in items], ['新款游戏手柄横评', '能用的结果'])

    def test_site_name_comes_from_domain(self):
        ws = tavily()
        ws._post = lambda path, body: {'results': TAVILY_RAW}
        self.assertEqual(ws.search('手柄推荐')[0]['site_name'], 'example.com')

    def test_request_body_shape(self):
        seen = {}
        ws = tavily({'count': 7})

        def fake_post(path, body):
            seen['path'], seen['body'] = path, body
            return {'results': []}
        ws._post = fake_post
        ws.search('最新手机', ori_question='最新手机哪款好', aliases=['年糕'])
        self.assertEqual(seen['path'], '/search')
        self.assertEqual(seen['body']['query'], '最新手机')
        self.assertEqual(seen['body']['max_results'], 7)
        self.assertEqual(seen['body']['search_depth'], 'basic')
        self.assertNotIn('ori_question', seen['body'])     # Tavily 没这个字段

    def test_search_depth_and_its_guard(self):
        seen = {}
        ws = tavily({'search_depth': 'advanced'})
        ws._post = lambda path, body: seen.update(body) or {'results': []}
        ws.search('最新手机')
        self.assertEqual(seen['search_depth'], 'advanced')
        ws2 = tavily({'search_depth': 'ADVANCED '})       # 大小写/空格要能容错
        ws2._post = lambda path, body: seen.update(body) or {'results': []}
        ws2.search('最新手机')
        self.assertEqual(seen['search_depth'], 'advanced')
        ws3 = tavily({'search_depth': '乱写'})
        ws3._post = lambda path, body: seen.update(body) or {'results': []}
        ws3.search('最新手机')
        self.assertEqual(seen['search_depth'], 'basic')    # 认不出来就用便宜的

    def test_max_results_clamped(self):
        seen = {}
        ws = tavily({'count': 500})
        ws._post = lambda path, body: seen.update(body) or {'results': []}
        ws.search('最新手机')
        self.assertEqual(seen['max_results'], 20)          # Tavily 上限 20

    def test_extra_body_merges(self):
        seen = {}
        ws = tavily({'extra_body': {'topic': 'news', 'days': 3}})
        ws._post = lambda path, body: seen.update(body) or {'results': []}
        ws.search('最新手机')
        self.assertEqual(seen['topic'], 'news')
        self.assertEqual(seen['days'], 3)

    def test_cache_prevents_second_request(self):
        calls = []
        ws = tavily()
        ws._post = lambda path, body: calls.append(1) or {'results': TAVILY_RAW}
        ws.search('手柄推荐')
        ws.search('手柄推荐')
        self.assertEqual(len(calls), 1)

    def test_cache_expiry_triggers_new_request(self):
        calls = []
        ws = tavily({'cache_ttl': 0})
        ws._post = lambda path, body: calls.append(1) or {'results': TAVILY_RAW}
        ws.search('手柄推荐')
        ws.search('手柄推荐')
        self.assertEqual(len(calls), 2)

    def test_cache_is_namespaced_per_provider(self):
        """同一句话换 provider 必须重新查：两个 provider 的结构不能互相解析。"""
        calls = []
        ws = tavily()
        ws._post = lambda path, body: calls.append(1) or {'results': TAVILY_RAW}
        ws.search('手柄推荐')
        ws.configure({'provider': 'deepseek'})
        ws._post = lambda path, body: calls.append(1) or {'results': DEEPSEEK_RAW}
        ws.search('手柄推荐')
        self.assertEqual(len(calls), 2)

    def test_hourly_cap(self):
        calls = []
        ws = tavily({'max_per_hour': 2})
        ws._post = lambda path, body: calls.append(1) or {'results': TAVILY_RAW}
        for i in range(4):
            ws.search('查询%d' % i)
        self.assertEqual(len(calls), 2)
        self.assertIn('上限', ws.last_error)

    def test_http_error_is_swallowed(self):
        import urllib.error

        def boom(path, body):
            raise urllib.error.HTTPError('https://x', 500, 'err', {}, None)
        ws = tavily()
        ws._post = boom
        self.assertEqual(ws.search('最新手机'), [])
        self.assertIn('500', ws.last_error)

    def test_network_error_is_swallowed(self):
        import urllib.error

        def boom(path, body):
            raise urllib.error.URLError('offline')
        ws = tavily()
        ws._post = boom
        self.assertEqual(ws.search('最新手机'), [])

    def test_bad_json_shape(self):
        ws = tavily()
        ws._post = lambda path, body: {'nope': 1}
        self.assertEqual(ws.search('最新手机'), [])
        self.assertIn('results', ws.last_error)

    def test_call_log_records_provider(self):
        ws = tavily()
        ws._post = lambda path, body: {'results': TAVILY_RAW}
        ws.search('手柄推荐')
        row = ws.db.execute('SELECT provider, ok FROM web_search_calls').fetchone()
        self.assertEqual(row[0], 'tavily')
        self.assertEqual(row[1], 1)


class DeepSeekProviderTests(unittest.TestCase):
    """切回 DeepSeek 时仍然按它自己的规矩跑（保留回滚能力）。"""

    def test_request_body_shape(self):
        seen = {}
        ws = deepseek({'count': 7})

        def fake_post(path, body):
            seen['path'], seen['body'] = path, body
            return {'results': []}
        ws._post = fake_post
        ws.search('最新手机', ori_question='最新手机哪款好', aliases=['年糕'])
        self.assertEqual(seen['path'], '/v1/tools/search')
        self.assertEqual(seen['body']['count'], 7)
        self.assertEqual(seen['body']['ori_question'], '最新手机哪款好')
        self.assertNotIn('need_content', seen['body'])

    def test_need_content_switch(self):
        seen = {}
        ws = deepseek({'need_content': True})
        ws._post = lambda path, body: seen.update(body) or {'results': []}
        ws.search('最新手机')
        self.assertTrue(seen['need_content'])

    def test_own_score_threshold_keeps_high_score_only(self):
        ws = deepseek()
        ws._post = lambda path, body: {'results': DEEPSEEK_RAW}
        self.assertEqual([i['title'] for i in ws.search('手柄推荐')],
                         ['新款游戏手柄横评', '能用的结果'])

    def test_unsafe_summary_falls_back_to_snippet(self):
        ws = deepseek()
        ws._post = lambda path, body: {'results': DEEPSEEK_RAW}
        item = [i for i in ws.search('手柄推荐') if i['title'] == '能用的结果'][0]
        self.assertEqual(item['summary'], '短摘要')


class FetchTests(unittest.TestCase):
    def test_without_key(self):
        ws = tavily(key='')
        self.assertEqual(ws.fetch('https://example.com'), '')

    def test_tavily_extract_reads_raw_content(self):
        seen = {}
        ws = tavily()

        def fake_post(path, body):
            seen['path'], seen['body'] = path, body
            return {'results': [{'url': 'https://example.com', 'raw_content': '# 手柄评测\n手感不错'}],
                    'failed_results': []}
        ws._post = fake_post
        self.assertIn('手感不错', ws.fetch('https://example.com'))
        self.assertEqual(seen['path'], '/extract')
        self.assertEqual(seen['body']['urls'], ['https://example.com'])

    def test_tavily_failed_result_gives_empty(self):
        ws = tavily()
        ws._post = lambda path, body: {'results': [], 'failed_results': [{'url': 'x'}]}
        self.assertEqual(ws.fetch('https://example.com'), '')

    def test_deepseek_fetch_shape(self):
        seen = {}
        ws = deepseek()

        def fake_post(path, body):
            seen['path'], seen['body'] = path, body
            return {'title': 't', 'content': '# 手柄评测\n手感不错'}
        ws._post = fake_post
        self.assertIn('手感不错', ws.fetch('https://example.com'))
        self.assertEqual(seen['path'], '/v1/tools/fetch')
        self.assertEqual(seen['body'], {'url': 'https://example.com'})

    def test_filters_unsafe_content(self):
        ws = tavily()
        ws._post = lambda path, body: {'results': [{'raw_content': '这里讲政治敏感内容'}]}
        self.assertEqual(ws.fetch('https://example.com'), '')


class FetchTop1Tests(unittest.TestCase):
    """fetch_top1=true 时：第一条结果的摘要换成正文，抓不到就保持原样。"""

    def test_top1_body_replaces_summary(self):
        ws = tavily({'fetch_top1': True})

        def fake_post(path, body):
            if path == '/extract':
                return {'results': [{'raw_content': '正文：三款手柄里这一款摇杆最跟手'}]}
            return {'results': TAVILY_RAW}
        ws._post = fake_post
        items = ws.search('手柄推荐')
        self.assertIn('摇杆最跟手', items[0]['summary'])
        self.assertTrue(items[0]['body_fetched'])

    def test_top1_fetch_failure_keeps_summary(self):
        import urllib.error
        ws = tavily({'fetch_top1': True})

        def fake_post(path, body):
            if path == '/extract':
                raise urllib.error.URLError('offline')
            return {'results': TAVILY_RAW}
        ws._post = fake_post
        items = ws.search('手柄推荐')
        self.assertEqual(items[0]['summary'], '三款国产手柄的手感对比')

    def test_top1_off_by_default(self):
        seen = []
        ws = tavily()
        ws._post = lambda path, body: seen.append(path) or {'results': TAVILY_RAW}
        ws.search('手柄推荐')
        self.assertEqual(seen, ['/search'])


class BreakerTests(unittest.TestCase):
    """401/402/403 这类是配置问题，不是网络抖动：要翻成人话，还要熔断止损。"""

    def http_error(self, code):
        import urllib.error
        return urllib.error.HTTPError('https://x', code, 'err', {}, None)

    def failing(self, ws, code=402):
        def boom(path, body):
            raise self.http_error(code)
        ws._post = boom
        return ws

    def test_402_says_out_of_balance(self):
        ws = self.failing(tavily())
        ws.search('最新手机')
        self.assertIn('余额不足', ws.last_error)

    def test_401_says_bad_key(self):
        ws = self.failing(tavily(), 401)
        ws.search('最新手机')
        self.assertIn('认证失败', ws.last_error)

    def test_unknown_code_keeps_raw_code(self):
        ws = self.failing(tavily(), 599)
        ws.search('最新手机')
        self.assertIn('599', ws.last_error)

    def test_breaker_stops_calling_after_three_failures(self):
        calls = []
        ws = tavily({'breaker_after': 3, 'breaker_seconds': 600})

        def boom(path, body):
            calls.append(1)
            raise self.http_error(402)
        ws._post = boom
        for i in range(6):
            ws.search('查询%d' % i)
        self.assertEqual(len(calls), 3)          # 熔断后一次网络都不再打
        self.assertTrue(ws.circuit_open())
        self.assertIn('已暂停搜索', ws.last_error)

    def test_success_resets_the_streak(self):
        ws = tavily({'breaker_after': 3})
        state = {'fail': True}

        def post(path, body):
            if state['fail']:
                raise self.http_error(402)
            return {'results': TAVILY_RAW}
        ws._post = post
        ws.search('a')
        ws.search('b')
        state['fail'] = False
        ws.search('c')                           # 成功一次，计数归零
        state['fail'] = True
        ws.search('d')
        ws.search('e')
        self.assertFalse(ws.circuit_open())      # 没到 3 连败，不该开

    def test_configure_resets_the_breaker(self):
        ws = tavily({'breaker_after': 1, 'breaker_seconds': 600})
        ws._post = lambda path, body: {'results': TAVILY_RAW}
        self.failing(ws)
        ws.search('查询')                        # 触发熔断
        self.assertTrue(ws.circuit_open())
        ws.configure({'provider': 'tavily', 'breaker_after': 1, 'breaker_seconds': 600})
        self.assertFalse(ws.circuit_open())      # 改完配置立刻能再试

    def test_cache_still_serves_while_circuit_open(self):
        ws = tavily({'breaker_after': 1, 'breaker_seconds': 600})
        ws._post = lambda path, body: {'results': TAVILY_RAW}
        first = [i['title'] for i in ws.search('手柄推荐')]
        self.assertTrue(first)
        self.failing(ws)
        ws.search('另一个查询')                   # 这一下把熔断打开
        self.assertTrue(ws.circuit_open())
        self.assertEqual([i['title'] for i in ws.search('手柄推荐')], first)


class MigrationTests(unittest.TestCase):
    """老库平滑升级：先上的 DeepSeek 版没有 provider 列，ALTER 必须自己补上。"""

    def test_old_schema_gets_provider_column(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        # 旧结构（照抄第一版建表语句，故意不含 provider）
        db.execute('CREATE TABLE web_search_cache('
                   ' query TEXT PRIMARY KEY, payload TEXT, fetched REAL)')
        db.execute('CREATE TABLE web_search_calls('
                   ' id INTEGER PRIMARY KEY, ts REAL, query TEXT, ok INTEGER,'
                   ' items INTEGER, error TEXT)')
        db.execute("INSERT INTO web_search_calls(ts,query,ok,items,error)"
                   " VALUES(?,?,?,?,?)", (time.time() - 10, '旧记录', 0, 0, 'HTTP 402'))
        db.commit()
        ws = WebSearch(db, {'provider': 'tavily'})          # 建表/迁移在构造里发生
        cols = {row[1] for row in db.execute('PRAGMA table_info(web_search_calls)')}
        self.assertIn('provider', cols)
        ws.key = lambda: 'test-key'
        ws._post = lambda path, body: {'results': TAVILY_RAW}
        ws.search('手柄推荐')                                # 迁移后写入不能炸
        rows = db.execute('SELECT provider FROM web_search_calls ORDER BY id').fetchall()
        self.assertEqual(rows[0][0], None)                  # 老记录留着，provider 为空
        self.assertEqual(rows[-1][0], 'tavily')

    def test_repeat_migration_is_idempotent(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        for _ in range(3):
            WebSearch(db, {'provider': 'tavily'})
        cols = [row[1] for row in db.execute('PRAGMA table_info(web_search_calls)')]
        self.assertEqual(cols.count('provider'), 1)


class HealthTests(unittest.TestCase):
    def test_health_reports_provider_and_fallback(self):
        ws = make({'provider': 'tavli'})
        health = ws.health()
        self.assertEqual(health['provider'], 'tavily')
        self.assertEqual(health['provider_fallback_from'], 'tavli')
        self.assertTrue(health['key_present'])


if __name__ == '__main__':
    unittest.main()
