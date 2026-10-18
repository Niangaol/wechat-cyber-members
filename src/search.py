"""RSSHub 热榜缓存：让机器人接得住网络热梗/时效性问题。公共实例限流，必须缓存。"""
import re, sqlite3, time, urllib.request
import xml.etree.ElementTree as ET

CACHE_TTL = 600          # 热榜缓存 10 分钟
FETCH_TIMEOUT = 15
MAX_ITEMS = 12           # 每个源最多存几条

# 公共实例列表（2026-10-15 实测：woodland 可用，rssforever 限流503，app 被墙；按序故障转移）
INSTANCES = [
    'https://rsshub.woodland.cafe',
    'https://rsshub.rssforever.com',
    'https://rsshub.ktachibana.party',
    'https://rsshub.app',
]

# Awesome RSSHub Routes 里常用的热榜路由
ROUTES = [
    ('weibo_hot', '/weibo/search/hot', '微博热搜'),
    ('bilibili_hot', '/bilibili/ranking', 'B站热榜'),
    ('zhihu_hot', '/zhihu/hotlist', '知乎热榜'),
    ('baidu_hot', '/baidu/top', '百度热点'),
    ('douyin_hot', '/douyin/hot', '抖音热点'),
    ('v2ex_hot', '/v2ex/topics/hot', 'V2EX 热帖'),
]

# 触发搜索的消息特征（时效性/热梗）
#
# 2026-10-18 扩了一档"要查真东西"的问法（用户拍板）。起因是实机漏搜：
# 群里问「dsv4.1flash1017 版本怎么样」，一个字都没命中旧表，机器人只能回
# "没查到具体信息"——搜索功能等于没接。
# 新加的这档（版本/更新/发布/多少钱/价格/参数/对比/哪款/哪个好/推荐/靠谱吗/怎么样）
# 会让更多问法去联网查，但三条闸门兜着：# 缓存 10 分钟（同句只花一次）、
# 每小时真实请求上限 30（max_per_hour）、连续失败自动熔断。Tavily 免费额度
# 1000 credits/月、basic 1 credit/次，正常用量够用。
# 嫌吵就往回删词——这条正则同时决定"要不要刷热榜"，改小了两边都变安静。
TRIGGER = re.compile(
    r'热搜|热点|热梗|梗|最新|最近|今天|昨天|今晚|新闻|发生了|怎么回事|流行|火了|刷屏|'
    r'热搜榜|头条|趋势|什么瓜|吃瓜|出什么事|news|trending|'
    r'版本|更新|发布|多少钱|价格|参数|对比|哪款|哪个好|推荐|靠谱吗|怎么样', re.I)


def clean(text):
    text = re.sub(r'<[^>]{1,80}>', '', str(text or ''))
    return re.sub(r'\s+', ' ', text).strip()[:200]


def needs_search(text):
    return bool(TRIGGER.search(str(text or '')))


class HotFeed:
    def __init__(self, db):
        self.db = db
        self.db.execute('CREATE TABLE IF NOT EXISTS hot_items('
                        ' id INTEGER PRIMARY KEY, source TEXT, source_name TEXT,'
                        ' title TEXT, link TEXT, fetched REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS hot_meta(source TEXT PRIMARY KEY, fetched REAL)')
        self.db.commit()

    def _fetch(self, url):
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; HotBot/1.0)'})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            data = resp.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('RSS 过大')
        return data

    def refresh(self, only_source=None, force=False):
        """拉取热榜入库；每个源按实例列表故障转移。返回成功源数。"""
        now = time.time()
        ok = 0
        for source, route, name in ROUTES:
            if only_source and source != only_source:
                continue
            row = self.db.execute('SELECT fetched FROM hot_meta WHERE source=?', (source,)).fetchone()
            if row and not force and now - row[0] < CACHE_TTL:
                continue
            got = False
            for base in INSTANCES:
                try:
                    root = ET.fromstring(self._fetch(base + route))
                except Exception:
                    continue  # 换下一个实例
                got = True
                break
            if not got:
                # 一个源在所有实例上都拉不到时也要记一笔"试过了"：否则按"最久没刷"
                # 轮转时会永远盯着这个死源（2026-10-17 实测 zhihu 路由拉不到）。
                # hot_meta 这里语义是"最近一次尝试时间"，只影响重试节奏，不影响数据。
                self.db.execute('INSERT OR REPLACE INTO hot_meta(source,fetched) VALUES(?,?)',
                                (source, now))
                self.db.commit()
                continue
            items = root.findall('.//item')[:MAX_ITEMS]
            if items:
                for it in items:
                    t = it.findtext('title') or ''
                    l = it.findtext('link') or ''
                    if t:
                        self._save(source, name, clean(t), l.strip(), now)
            else:  # Atom 格式兜底
                ns = {'a': 'http://www.w3.org/2005/Atom'}
                for e in root.findall('.//a:entry', ns)[:MAX_ITEMS]:
                    t = e.findtext('a:title', default='', namespaces=ns)
                    l = e.findtext('a:link', default='', namespaces=ns) or ''
                    if t:
                        self._save(source, name, clean(t), l.strip(), now)
            self.db.execute('INSERT OR REPLACE INTO hot_meta(source,fetched) VALUES(?,?)',
                            (source, now))
            self._prune(source)
            self.db.commit()
            ok += 1
            time.sleep(1)  # 对公共实例温柔一点
        return ok

    def _prune(self, source, keep=40):
        """每个源只留最近 keep 条。

        热榜标题天天在变，不去重清理的话这张表会慢慢涨（一天百来条、一年几万条）。
        只影响历史缓存；接梗用的是最近条目，不受影响。
        """
        self.db.execute(
            'DELETE FROM hot_items WHERE source=? AND id NOT IN ('
            ' SELECT id FROM hot_items WHERE source=? ORDER BY fetched DESC, id DESC LIMIT ?)',
            (source, source, int(keep)))

    def _save(self, source, name, title, link, now):
        self.db.execute('DELETE FROM hot_items WHERE source=? AND title=?', (source, title))
        self.db.execute('INSERT INTO hot_items(source,source_name,title,link,fetched)'
                        ' VALUES(?,?,?,?,?)', (source, name, title, link, now))

    def freshness(self):
        """最新缓存时间；没有任何缓存返回 0。"""
        row = self.db.execute('SELECT max(fetched) FROM hot_meta').fetchone()
        return row[0] or 0

    def relevant(self, query, limit=6):
        """按消息关键词匹配热榜标题；命中不足就退化为最新热榜。

        热榜是公开数据，可能带时政/敏感内容；注入模型前必须过安全闸，
        否则模型可能顺着话题输出敏感回复（违反"所有输出避开敏感话题"）。
        """
        from moments_safe import is_safe
        q = str(query or '')
        terms = [t for t in re.split(r'[\s，。！？、,?!]+', q) if len(t) >= 2][:6]
        rows = self.db.execute(
            'SELECT source_name,title,link FROM hot_items ORDER BY fetched DESC, id DESC'
            ' LIMIT 200').fetchall()
        if not rows:
            return []
        safe = [r for r in rows if is_safe(r[1])[0]]
        hits = [r for r in safe if any(t.lower() in r[1].lower() for t in terms)] if terms else []
        if len(hits) < limit:
            seen = {h[1] for h in hits}
            hits += [r for r in safe if r[1] not in seen][:limit - len(hits)]
        return [{'source': r[0], 'title': r[1], 'link': r[2]} for r in hits[:limit]]
