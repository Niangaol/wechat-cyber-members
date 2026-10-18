"""联网搜索的实机冒烟测试：真的打一次搜索 API（默认 Tavily）。

用法（WSL 里，key 已 export 的情况下）：
    cd /mnt/d/AgentPrograms/wechat-bot && python3 wsl/check-search.py "最新手柄"
不传 query 就用默认词。它会按 config/resident.json 里的真实参数跑一遍，打印：
用的哪个 provider、key 从哪来、耗时、过滤前后条数、以及每条结果的标题/链接/摘要。

只在你有 key 的时候用；没 key 它会明确告诉你缺什么，不会静默失败。
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from web_search import WebSearch        # noqa: E402


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else 'DeepSeek V4 模型 发布'
    block = (json.loads((ROOT / 'config' / 'resident.json').read_text(encoding='utf-8'))
             or {}).get('web_search') or {}
    ws = WebSearch(sqlite3.connect(':memory:'), block)
    cfg = ws.cfg
    env_name = str(cfg.get('api_key_env') or '')
    source = ('env %s' % env_name if env_name and os.environ.get(env_name)
              else 'credentials.json 的 %s' % cfg.get('credential_key'))
    print('provider   :', ws.provider)
    print('端点       :', str(cfg.get('base_url')) + ws._search_path())
    print('query      :', query)
    print('key 来源   :', source)
    print('key 就绪   :', bool(ws.key()))
    if not ws.key():
        print('没有 key，联调不了。任选一种：')
        print('  export %s=<你的 key>' % (env_name or 'TAVILY_API_KEY'))
        print('  或写进 ~/.local/state/wechat-bot/credentials.json 的 %s 字段'
              % (cfg.get('credential_key') or 'tavily_api_key'))
        return 2
    started = time.time()
    items = ws.search(query)
    print('耗时       : %.2fs' % (time.time() - started))
    print('过滤后条数 : %d    last_error=%r' % (len(items), ws.last_error))
    for index, item in enumerate(items, 1):
        print('%d. [score=%s] %s' % (index, item.get('score'), item.get('title')))
        print('   %s' % item.get('url'))
        print('   %s' % (item.get('summary') or '')[:160])
    if not items:
        if ws.last_error:
            print('这次没成功：上面 last_error 就是原因。')
        else:
            print('接口通了但一条都没剩下：多半是全被安全黑名单筛掉了'
                  '（这是有意为之——宁可没资料，也不带敏感内容进 prompt）。')
    return 0 if items else 1


if __name__ == '__main__':
    raise SystemExit(main())
