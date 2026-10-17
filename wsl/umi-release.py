import json, urllib.request
url = 'https://api.github.com/repos/hiroi-sora/Umi-OCR/releases/tags/v2.1.5'
req = urllib.request.Request(url, headers={'User-Agent': 'wechat-bot-check', 'Accept': 'application/vnd.github+json'})
try:
    with urllib.request.urlopen(req, timeout=25) as r:
        d = json.loads(r.read())
except Exception as e:
    print(json.dumps({'error': type(e).__name__, 'detail': str(e)[:200]}))
    raise SystemExit(0)
print('tag:', d.get('tag_name'))
print('name:', d.get('name'))
print('published:', d.get('published_at'))
print('assets:')
for a in d.get('assets', []):
    print('  %-46s %10d  %s' % (a['name'], a['size'], a['browser_download_url']))
