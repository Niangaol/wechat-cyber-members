"""Live verification of link comprehension and RSSHub hot feed (read-only, no WeChat)."""
import json, sqlite3, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from web_reader import fetch_public_text, WebSafetyError, public_endpoint
from search import HotFeed, needs_search

LINKS_CFG = {'timeout': 12, 'max_bytes': 250000, 'max_chars': 9000}
CASES = [
    ('https://example.com/', '普通静态页'),
    ('http://127.0.0.1/', '本机地址应被拒'),
    ('file:///etc/passwd', '非HTTP应被拒'),
    ('https://example.com:8443/', '非标准端口应被拒'),
]

print('=== 链接理解', flush=True)
for url, note in CASES:
    t = time.perf_counter()
    try:
        r = fetch_public_text(url, LINKS_CFG)
        text = r['untrusted_text']
        print(json.dumps({'url': url, 'note': note, 'ok': True, 'status': r['status'],
                          'chars': len(text), 'preview': ' '.join(text[:90].split()),
                          'seconds': round(time.perf_counter()-t, 2)}, ensure_ascii=False), flush=True)
    except WebSafetyError as e:
        print(json.dumps({'url': url, 'note': note, 'ok': False, 'reason': str(e),
                          'seconds': round(time.perf_counter()-t, 2)}, ensure_ascii=False), flush=True)
    except Exception as e:
        print(json.dumps({'url': url, 'note': note, 'ok': False, 'error': type(e).__name__,
                          'detail': str(e)[:120]}), flush=True)

print('=== 触发词判定', flush=True)
for text in ['今天有什么热搜', '在吗', '这个梗是什么', '最新消息']:
    print(json.dumps({'text': text, 'needs_search': needs_search(text)}, ensure_ascii=False), flush=True)

print('=== RSSHub 热榜', flush=True)
with tempfile.TemporaryDirectory() as td:
    feed = HotFeed(sqlite3.connect(':memory:'))
    t = time.perf_counter()
    ok = feed.refresh()
    rows = feed.db.execute('SELECT source,count(*) FROM hot_items GROUP BY source').fetchall()
    print(json.dumps({'sources_ok': ok, 'per_source': rows,
                      'seconds': round(time.perf_counter()-t, 1)}, ensure_ascii=False), flush=True)
    sample = feed.db.execute('SELECT source,title FROM hot_items LIMIT 5').fetchall()
    for s, title in sample:
        print(json.dumps({'sample': s, 'title': title[:70]}, ensure_ascii=False), flush=True)
    print(json.dumps({'relevant_test': feed.relevant('今天微博热搜是什么')[:2]}, ensure_ascii=False), flush=True)
