"""联网搜索接入：默认 Tavily（POST https://api.tavily.com/search），可切回 DeepSeek。

分工（别和 search.py 搞混）：
- search.py 管 RSSHub 热榜缓存：免费、公共实例、慢，回答"最近大家在聊什么"；
- 这个模块管"用户问的事实性问题，去网上查一下"：要 key、要钱，
  所以必须带缓存和每小时上限，否则群里一句"最新手机哪款好"就能刷出一堆调用。

三条规矩（和热榜一致，别拆）：
1. 搜索结果全是**不可信外部资料**，只进 user JSON，绝不拼进 system；
2. 每条都要过 moments_safe.is_safe，政治/灾难/色情/证件类直接丢——命中就当没搜到，
   宁可让模型说"我查不到最新的"，也不带脏数据进 prompt；
3. 任何失败（没 key / 超时 / 429 / 返回不是 JSON）都只返回 []，绝不抛异常打断回复。

两个 provider 的差别（都实测过，别照抄对方的参数）：
- Tavily：score 是 **0~1** 的相关度，返回的 content 就是抽好的正文（实测 1400 字左右）；
  basic 搜索 1 credit/次、advanced 2 credits/次；免费额度 1000 credits/月。
- DeepSeek：rerank_score 是 **0~3**，summary 是官方给模型读的 600~800 字摘要；
  5 元 / 1000 次成功请求。**量纲不同，min_score 必须分开配**，否则要么全丢要么全留。

文档：Tavily https://docs.tavily.com/documentation/api-reference/introduction
      DeepSeek https://api-docs.deepseek.com/zh-cn/guides/search
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from moments_safe import is_safe
from model_api import STATE, load_credentials

DEFAULT_PROVIDER = 'tavily'

# 值本身是字典的配置项：合并时不能当标量跳过，得单独搬过来
DICT_KEYS = ('extra_body',)

# 每个 provider 的出厂默认。切换 provider 只改配置里的一行，其余跟着走。
PROVIDERS = {
    'tavily': {
        'base_url': 'https://api.tavily.com',
        'api_key_env': 'TAVILY_API_KEY',
        'credential_key': 'tavily_api_key',
        'count': 5,              # max_results，官方 0~20
        'search_depth': 'basic', # basic=1 credit，advanced=2 credits
        'min_score': 0.3,        # Tavily 是 0~1 的相关度：0.3 以下基本是凑数的
    },
    'deepseek': {
        'base_url': 'https://api.deepseek.com',
        'api_key_env': 'DEEPSEEK_API_KEY',
        'credential_key': 'deepseek_api_key',
        'count': 5,              # 接口上限 50
        'need_content': False,   # True 会连网页正文一起返回，更准也更慢
        'min_score': 1.2,        # DeepSeek 是 0~3（官方说 >=1.5 为优质，留点余量）
    },
}

# 与 provider 无关的公共项。
DEFAULTS = {
    'enabled': True,
    'provider': DEFAULT_PROVIDER,
    'credential_file': 'credentials.json',
    'timeout': 8,             # 实测 Tavily basic 1.8 秒；聊天回合里 8 秒是封顶
    'cache_ttl': 600,         # 同一句话 10 分钟内重复问，直接吃缓存不花钱
    'max_per_hour': 30,       # 每小时真实请求上限：防刷、防失控账单
    'max_items': 5,           # 最多注入几条
    'max_summary_chars': 500, # 单条摘要截断（Tavily 的 content 有 1400+ 字，必须截）
    'max_query_chars': 120,
    'use_content': False,     # 是否允许把正文喂给模型
    'fetch_top1': False,      # 是否对第一条结果再抓一次正文（多一次网络往返）
    'breaker_after': 3,       # 连续失败几次就暂停搜索（别每次触发都白等一次网络）
    'breaker_seconds': 600,   # 暂停多久；期间静默走热榜兜底
    'extra_body': {},         # 想用 provider 的其它参数（topic/days/include_answer…）塞这里
}


def cfg_of(block):
    """合并配置：公共默认 → provider 出厂默认 → 顶层显式项 → provider 专属子块。

    子块最后合并，因为"专门写给这个 provider 的配置"意图最强。下划线开头的键是
    给人看的注释，一律跳过。
    """
    clean = {k: v for k, v in (block or {}).items() if not str(k).startswith('_')}
    requested = str(clean.get('provider') or DEFAULT_PROVIDER)
    # provider 名字拼错时**必须**退回默认并留痕：否则会拿着 A 的请求格式去打 B 的
    # 端点（两个 provider 的路径和字段名完全不同），报出来的错谁也看不懂。
    name = requested if requested in PROVIDERS else DEFAULT_PROVIDER
    merged = dict(DEFAULTS)
    merged.update(PROVIDERS.get(name, {}))
    # 顶层标量配置覆盖出厂默认；值为字典的项要单独认（provider 子块就是字典，
    # 不能当标量合并），否则像 extra_body 这种"值本身是字典"的配置会被悄悄吃掉。
    merged.update({k: v for k, v in clean.items() if not isinstance(v, dict)})
    for key in DICT_KEYS:
        value = clean.get(key)
        if isinstance(value, dict):
            merged[key] = {k: v for k, v in value.items() if not str(k).startswith('_')}
    sub = clean.get(name)
    if isinstance(sub, dict):
        merged.update({k: v for k, v in sub.items() if not str(k).startswith('_')})
    merged['provider'] = name
    if requested != name:
        merged['provider_fallback_from'] = requested
    return merged


def build_query(text, aliases=(), max_chars=120):
    """把一堆聊天消息压成一条搜索词。

    机器人在群里被喊"年糕 最新手机哪款好"时，搜索词里带着自己的名字只会污染结果，
    所以先把别名和 @xxx 剥掉；再压空白、截断到接口允许的长度。
    """
    query = str(text or '')
    # 顺序有讲究：先剥 @xxx（微信里 @ 后面紧跟昵称，允许带空格前的整段），
    # 再剥别名——反过来的话"@年糕Agent"会剩下一个孤零零的 '@' 进搜索词。
    query = re.sub(r'@\s*\S+', ' ', query)
    for alias in aliases or ():
        if alias:
            query = query.replace(str(alias), ' ')
    query = query.replace('@', ' ')
    query = re.sub(r'\s+', ' ', query).strip()
    try:
        limit = max(1, int(max_chars))
    except (TypeError, ValueError):
        limit = 120
    return query[:limit]


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _site_of(url):
    """从 URL 取站点名：Tavily 不返回 site_name，只能自己从域名推。"""
    try:
        host = (urlsplit(str(url or '')).hostname or '').lower()
    except ValueError:
        return ''
    return host[4:] if host.startswith('www.') else host


class WebSearch:
    """一个搜索客户端 = 一张缓存表 + 一个调用计数表 + 一份配置。

    provider 只影响"怎么问、怎么解析"，缓存/上限/熔断/安全过滤四件事对所有
    provider 是同一套——它们才是真正防账单和防脏数据的地方。
    """

    def __init__(self, db, block=None):
        self.db = db
        self.cfg = cfg_of(block)
        self.provider = str(self.cfg.get('provider') or DEFAULT_PROVIDER)
        self.last_error = ''
        self.last_searched_at = 0.0
        self._fail_streak = 0
        self._open_until = 0.0
        self._ensure_tables()

    def configure(self, block):
        """配置热更新：改 config/resident.json 不用重启也能生效。

        顺手把熔断清掉：402/401 这类是"改了配置就能好"的问题，用户改完配置
        （或重启服务）就该立刻恢复，不该还被十分钟的暂停期按着。
        """
        self.cfg = cfg_of(block)
        self.provider = str(self.cfg.get('provider') or DEFAULT_PROVIDER)
        if not self.circuit_open():
            return self
        self.note_success()
        self.last_error = ''
        return self

    # ---------- 存储 ----------
    def _ensure_tables(self):
        # 缓存的是**原始**结果，安全过滤在读取时再做一遍：
        # 以后黑名单加了新词，旧缓存也会被重新筛，不用等 TTL 过期。
        self.db.execute('CREATE TABLE IF NOT EXISTS web_search_cache('
                        ' query TEXT PRIMARY KEY, payload TEXT, fetched REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS web_search_calls('
                        ' id INTEGER PRIMARY KEY, ts REAL, query TEXT, ok INTEGER,'
                        ' items INTEGER, error TEXT)')
        # provider 列是后加的（先上的 DeepSeek 版没有这列）：老库要能平滑升上来
        try:
            cols = {row[1] for row in self.db.execute('PRAGMA table_info(web_search_calls)')}
            if 'provider' not in cols:
                self.db.execute('ALTER TABLE web_search_calls ADD COLUMN provider TEXT')
        except Exception:                              # noqa: BLE001
            pass
        self.db.commit()

    def _cache_key(self, query):
        """缓存键带上 provider：同一个词在两个 provider 下的结果结构不一样，
        混在一起会让旧条目被新 provider 解析器当成自己的格式读。"""
        return '%s|%s' % (self.provider, query)

    def _cache_get(self, query):
        try:
            row = self.db.execute('SELECT payload, fetched FROM web_search_cache'
                                  ' WHERE query=?', (self._cache_key(query),)).fetchone()
        except Exception:                              # noqa: BLE001
            return None
        if not row:
            return None
        ttl = _as_float(self.cfg.get('cache_ttl'), 600)
        if ttl <= 0:                                   # 0 = 关掉缓存（调试/测试用）
            return None
        if time.time() - _as_float(row[1]) > ttl:
            return None
        try:
            payload = json.loads(row[0])
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, list) else None

    def _cache_put(self, query, raw):
        try:
            self.db.execute('INSERT OR REPLACE INTO web_search_cache(query,payload,fetched)'
                            ' VALUES(?,?,?)',
                            (self._cache_key(query),
                             json.dumps(raw, ensure_ascii=False), time.time()))
            # 搜索结果不像热榜那样高频复用，留最近 200 条就够，别让表无限长
            self.db.execute('DELETE FROM web_search_cache WHERE query NOT IN ('
                            ' SELECT query FROM web_search_cache ORDER BY fetched DESC LIMIT 200)')
            self.db.commit()
        except Exception:                              # noqa: BLE001
            pass

    def calls_last_hour(self):
        try:
            row = self.db.execute('SELECT count(*) FROM web_search_calls WHERE ts>?',
                                  (time.time() - 3600,)).fetchone()
            return int(row[0] or 0)
        except Exception:                              # noqa: BLE001
            return 0

    def _log_call(self, query, ok, items=0, error=''):
        try:
            self.db.execute('INSERT INTO web_search_calls(ts,query,ok,items,error,provider)'
                            ' VALUES(?,?,?,?,?,?)',
                            (time.time(), query[:120], 1 if ok else 0, int(items),
                             str(error)[:120], self.provider))
            self.db.commit()
        except Exception:                              # noqa: BLE001
            pass

    # ---------- 密钥 ----------
    def key(self):
        env = str(self.cfg.get('api_key_env') or '')
        if env and os.environ.get(env):
            return os.environ[env]
        creds = load_credentials(STATE / str(self.cfg.get('credential_file') or 'credentials.json'))
        # 只认显式写的键名：绝不回退到通用的 api_key，那是别的供应商的密钥，
        # 拿去打搜索接口只会吃一个 401，还容易让人误以为"key 配好了"。
        field = str(self.cfg.get('credential_key') or '')
        return str(creds.get(field) or '') if (creds and field) else ''

    def ready(self):
        return bool(self.cfg.get('enabled', True)) and bool(self.key())

    def health(self):
        return {'enabled': bool(self.cfg.get('enabled', True)),
                'provider': self.provider,
                'provider_fallback_from': self.cfg.get('provider_fallback_from'),
                'key_present': bool(self.key()),
                'calls_last_hour': self.calls_last_hour(),
                'max_per_hour': self.cfg.get('max_per_hour'),
                'circuit_open': self.circuit_open(),
                'last_error': self.last_error}

    # HTTP 状态码翻成人话：401/402/403 不是"网络抖一下"，是必须人去处理的配置问题，
    # 混在一句"HTTP 402"里没人看得懂，也就没人去修。
    # 认不出来的码（Tavily 有 432/433 这类额度码）就把响应体前 100 字带出来——
    # 服务端自己会说是余额、额度还是参数问题，比我瞎编一张对照表可靠。
    HTTP_REASONS = {
        400: '请求被拒(400)：参数不对',
        401: '认证失败(401)：key 不对或没带',
        402: '余额不足(402)：这把 key 付不了搜索的钱，需要充值或换 key',
        403: '无权限(403)：这把 key 不能用搜索接口',
        429: '限流(429)：调用太密，稍后自动恢复',
    }

    def _http_reason(self, exc):
        code = getattr(exc, 'code', 0)
        known = self.HTTP_REASONS.get(code)
        if known:
            return known
        detail = ''
        try:
            detail = exc.read(200).decode('utf-8', 'replace')
        except Exception:                              # noqa: BLE001
            detail = ''
        detail = re.sub(r'\s+', ' ', detail).strip()
        return ('HTTP %s %s' % (code, detail[:100])).strip()

    def _fail(self, query, reason):
        """记一次失败：写日志表 + 累加熔断计数；返回空列表让上层走热榜兜底。"""
        self.note_failure(reason)
        self._log_call(query, False, error=reason)
        return []

    # ---------- 熔断 ----------
    def circuit_open(self, now=None):
        return (time.time() if now is None else now) < self._open_until

    def note_success(self):
        self._fail_streak = 0
        self._open_until = 0.0

    def note_failure(self, reason):
        self.last_error = reason
        self._fail_streak += 1
        after = int(_as_float(self.cfg.get('breaker_after'), 3))
        if after > 0 and self._fail_streak >= after:
            wait = _as_float(self.cfg.get('breaker_seconds'), 600)
            self._open_until = time.time() + wait
            self._fail_streak = 0
            self.last_error = '%s（已暂停搜索 %d 秒）' % (reason, int(wait))

    # ---------- 请求组装（provider 相关） ----------
    def _request(self, query, ori_question, aliases):
        """返回 (path, body)：不同 provider 的路径和字段名完全不一样。"""
        try:
            count = max(1, int(_as_float(self.cfg.get('count'), 5)))
        except (TypeError, ValueError):
            count = 5
        if self.provider == 'tavily':
            body = {'query': query, 'max_results': max(1, min(20, count))}
            depth = str(self.cfg.get('search_depth') or 'basic').strip().lower()
            body['search_depth'] = depth if depth in ('basic', 'advanced') else 'basic'
        else:
            body = {'query': query, 'count': max(1, min(50, count))}
            if self.cfg.get('need_content') or self.cfg.get('use_content'):
                body['need_content'] = True
            # ori_question 只有 DeepSeek 认；Tavily 没有对应字段
            question = build_query(ori_question if ori_question is not None else query,
                                   aliases, self.cfg.get('max_query_chars', 120))
            if question:
                body['ori_question'] = question
        extra = self.cfg.get('extra_body')
        if isinstance(extra, dict):
            body.update({k: v for k, v in extra.items() if not str(k).startswith('_')})
        return self._search_path(), body

    def _search_path(self):
        return '/search' if self.provider == 'tavily' else '/v1/tools/search'

    def _extract_path(self):
        return '/extract' if self.provider == 'tavily' else '/v1/tools/fetch'

    # ---------- 网络 ----------
    def _post(self, path, body):
        base = str(self.cfg.get('base_url') or '').rstrip('/')
        if not base.startswith(('https://', 'http://')):
            raise ValueError('base_url 必须是 http(s) 地址')
        request = urllib.request.Request(
            base + path,
            json.dumps(body, ensure_ascii=False).encode('utf-8'),
            headers={'Authorization': 'Bearer ' + self.key(),
                     'Content-Type': 'application/json'})
        timeout = _as_float(self.cfg.get('timeout'), 8) or 8
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('搜索响应过大')
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise ValueError('搜索响应不是对象')
        return parsed

    # ---------- 主流程 ----------
    def search(self, text, ori_question=None, aliases=()):
        """按聊天内容搜一次，返回可直接注入 prompt 的条目列表（失败返回 []）。"""
        query = build_query(text, aliases, self.cfg.get('max_query_chars', 120))
        if not query or not query.strip():
            return []
        if not self.cfg.get('enabled', True):
            return []
        if not self.key():
            self.last_error = '未配置 %s key' % self.provider
            return []
        cached = self._cache_get(query)
        if cached is not None:
            return self._filter(cached)          # 缓存优先：熔断了也照样吃旧结果
        if self.circuit_open():
            return []                            # 熔断期间不打网络，静默走热榜兜底
        cap = int(_as_float(self.cfg.get('max_per_hour'), 30))
        if cap > 0 and self.calls_last_hour() >= cap:
            self.last_error = '本小时搜索次数已达上限 %d' % cap
            return []
        path, body = self._request(query, ori_question, aliases)
        try:
            parsed = self._post(path, body)
        except urllib.error.HTTPError as exc:
            return self._fail(query, self._http_reason(exc))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return self._fail(query, '网络/超时: %s' % type(exc).__name__)
        except (ValueError, UnicodeError) as exc:
            return self._fail(query, '响应异常: %s' % str(exc)[:60])
        raw = parsed.get('results')
        if not isinstance(raw, list):
            return self._fail(query, '响应缺少 results')
        self.last_searched_at = time.time()
        self.note_success()
        self.last_error = ''
        self._cache_put(query, raw)
        items = self._filter(raw)
        if items and self.cfg.get('fetch_top1'):
            items = self._enrich_top1(items)
        self._log_call(query, True, items=len(items))
        return items

    def _normalize(self, entry):
        """把某个 provider 的原始条目压成统一形状。

        统一形状：title/url/summary（给模型读的正文）/snippet（短摘要，可空）
        /content（更长的正文，可选）/site_name/date/score。
        """
        if self.provider == 'tavily':
            url = str(entry.get('url') or '').strip()
            return {'title': str(entry.get('title') or '').strip(),
                    'url': url,
                    'summary': str(entry.get('content') or '').strip(),
                    'snippet': '',                      # Tavily 没有短摘要字段
                    'content': str(entry.get('raw_content') or '').strip(),
                    'site_name': _site_of(url),
                    'date': '',                         # Tavily 不返回发布时间
                    'score': _as_float(entry.get('score'), 0.0)}
        url = str(entry.get('url') or '').strip()
        return {'title': str(entry.get('title') or '').strip(),
                'url': url,
                'summary': str(entry.get('summary') or '').strip(),
                'snippet': str(entry.get('snippet') or '').strip(),
                'content': str(entry.get('content') or '').strip(),
                'site_name': str(entry.get('site_name') or '').strip(),
                'date': str(entry.get('date') or '').strip(),
                'score': _as_float(entry.get('rerank_score'), 0.0)}

    def _filter(self, raw):
        """逐条过闸：分数太低、标题/摘要踩红线、链接不是 http(s) 的一律丢。"""
        min_score = _as_float(self.cfg.get('min_score'), 0.0)
        try:
            max_items = max(1, int(_as_float(self.cfg.get('max_items'), 5)))
        except (TypeError, ValueError):
            max_items = 5
        try:
            max_chars = max(80, int(_as_float(self.cfg.get('max_summary_chars'), 500)))
        except (TypeError, ValueError):
            max_chars = 500
        items = []
        for entry in raw or []:
            if not isinstance(entry, dict):
                continue
            item = self._normalize(entry)
            if not item['title'] or not item['url'].startswith(('http://', 'https://')):
                continue
            if item['score'] < min_score:
                continue
            if not is_safe(item['title'])[0]:
                continue                            # 标题踩线：整条丢
            snippet = item.get('snippet') or ''
            if snippet and not is_safe(snippet)[0]:
                continue                            # 短摘要踩线：整条丢
            summary = item.get('summary') or ''
            if summary and not is_safe(summary)[0]:
                summary = snippet                   # 长摘要踩线：退回短摘要
            if not summary:
                summary = snippet
            if self.cfg.get('use_content'):
                content = item.get('content') or ''
                if content and is_safe(content)[0]:
                    summary = content
            items.append({'title': item['title'][:80],
                          'url': item['url'],
                          'summary': re.sub(r'\s+', ' ', summary)[:max_chars],
                          'site_name': item['site_name'][:40],
                          'date': item['date'][:19],
                          'score': round(item['score'], 2)})
            if len(items) >= max_items:
                break
        return items

    def _enrich_top1(self, items):
        """可选增强：把第一条结果的正文抓下来替换它那条摘要。

        为什么要单独一个开关：这是额外一次网络往返，聊天回合里等不起，默认关。
        抓不到就原样返回——摘要还在，不因为"增强"失败把结果弄丢。
        """
        body = self.fetch(items[0].get('url'))
        if body:
            first = dict(items[0])
            first['summary'] = body
            first['body_fetched'] = True
            return [first] + list(items[1:])
        return items

    # ---------- 可选：抓正文 ----------
    def fetch(self, url):
        """单独抓一个页面正文（失败返回 ''）。默认不调用，fetch_top1 打开时才用。"""
        url = str(url or '').strip()
        if not url.startswith(('http://', 'https://')) or not self.key():
            return ''
        body = {'urls': [url]} if self.provider == 'tavily' else {'url': url}
        try:
            parsed = self._post(self._extract_path(), body)
        except Exception as exc:                       # noqa: BLE001
            self.last_error = '抓取失败: %s' % type(exc).__name__
            return ''
        if self.provider == 'tavily':
            # Tavily /extract 返回 results[]（成功）与 failed_results[]（失败）
            rows = parsed.get('results')
            content = ''
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                content = str(rows[0].get('raw_content') or rows[0].get('content') or '')
        else:
            content = str(parsed.get('content') or '')
        content = content.strip()
        if not content or not is_safe(content)[0]:
            return ''
        return content[:int(_as_float(self.cfg.get('max_summary_chars'), 500))]
