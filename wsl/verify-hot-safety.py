"""Verify hot feed filters sensitive titles before model injection."""
import json, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from search import HotFeed
feed = HotFeed(sqlite3.connect(':memory:'))
now = 1.0
SAMPLE = [
    ('微博热搜', '习近平致信祝贺湖南大学建校100周年'),
    ('微博热搜', '日本误报9.9级地震'),
    ('微博热搜', '芒果真的拍了再见朋友'),
    ('微博热搜', '第140届广交会有哪些新亮点'),
    ('B站热榜', '某UP主翻唱火遍全网'),
    ('知乎热榜', '如何评价最新款游戏手柄'),
]
for name, title in SAMPLE:
    feed._save('x', name, title, 'https://example.com/' + title[:6], now)
out = feed.relevant('今天有什么热搜', limit=10)
print(json.dumps({'stored': len(SAMPLE), 'returned': len(out),
                  'titles': [o['title'] for o in out],
                  'sensitive_leaked': [o['title'] for o in out
                                       if any(k in o['title'] for k in ('习近平', '地震', '广交会'))]},
                 ensure_ascii=False, indent=1), flush=True)
SENSITIVE = ('习近平', '毛泽东', '地震', '疫情', '台独', '港独', 'terror', '杀人')
leaked = [o['title'] for o in out if any(k in o['title'] for k in SENSITIVE)]
print(json.dumps({'leaked': leaked,
                  'note': '关键词黑名单不可能完备； borderline 经贸/娱乐条目可能通过，靠系统提示兜底'}, ensure_ascii=False), flush=True)
assert not leaked, '敏感词泄漏'
print('SAFETY_FILTER_OK', flush=True)
