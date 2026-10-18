"""实机验证：模型会不会自己调搜索工具、调几次、拿到什么、答得怎么样。

用法（WSL 里最省事，用的就是常驻服务那把 key）：
    cd /mnt/d/AgentPrograms/wechat-bot && python3 wsl/check-search-tool.py
Windows 上也能跑：会自动把凭据目录指到 WSL 那份。

它会跑三条真实对话（该搜的版本问题、不该搜的闲聊、该搜的时效推荐），
打印每段的耗时、模型给的搜索词、搜索条数，以及最终回复。
换模型之后想知道"工具调用还灵不灵"，就跑这个。
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

import model_api          # noqa: E402
import multimodal         # noqa: E402
import web_search         # noqa: E402

if os.name == 'nt':       # Windows 上跑：凭据在 WSL 侧，指过去
    _user = os.environ.get('WSL_USER') or 'niangao'
    _state = Path('//wsl.localhost/Ubuntu-24.04/home/%s/.local/state/wechat-bot' % _user)
    model_api.STATE = _state
    multimodal.STATE = _state
    web_search.STATE = _state

CFG = json.loads((ROOT / 'config' / 'resident.json').read_text(encoding='utf-8'))
BOX = {}


def search_fn(query):
    ws = BOX.get('ws')
    if ws is None:
        ws = BOX['ws'] = web_search.WebSearch(sqlite3.connect(':memory:'), CFG['web_search'])
    started = time.time()
    items = ws.search(query, ori_question=query, aliases=CFG.get('mention_aliases') or [])
    print('    [搜索] query=%r  %.2fs  条数=%d  err=%r'
          % (query, time.time() - started, len(items), ws.last_error))
    for item in items[:2]:
        print('           - [%.2f] %s' % (item['score'], item['title'][:52]))
    return items


class Observed(multimodal.StepPlan):
    """把两段式调用的时间和结果打出来，别的照原样。"""

    def call_turn(self, messages, max_tokens=1800, model=None, provider=None, tools=None):
        started = time.time()
        text, calls = super().call_turn(messages, max_tokens, model=model,
                                        provider=provider, tools=tools)
        print('    [模型·第1段] %.2fs  带工具=%s  → tool_calls=%d 个 %s'
              % (time.time() - started, bool(tools), len(calls),
                 json.dumps([c.get('function', {}).get('name') for c in calls if isinstance(c, dict)],
                            ensure_ascii=False)))
        return text, calls

    def call(self, messages, max_tokens=1800, model=None, provider=None):
        started = time.time()
        text = super().call(messages, max_tokens, model=model, provider=provider)
        print('    [模型·第2段] %.2fs  消息数=%d（含 tool 结果=%s）'
              % (time.time() - started, len(messages),
                 any(m.get('role') == 'tool' for m in messages)))
        return text


CASES = [
    ('该搜的：版本问题', 'dsv4.1flash1017 这个版本怎么样？'),
    ('不该搜的：闲聊', '在吗，吃了吗'),
    ('该搜的：时效推荐', '最近有什么值得买的国产手柄吗'),
]


def main():
    plan = Observed(CFG)
    print('模型:', CFG['step_plan']['model'], '@', CFG['step_plan']['base_url'])
    print('搜索 provider:', CFG['web_search'].get('provider'))
    for label, text in CASES:
        print()
        print('=== %s ===' % label)
        print('  用户:', text)
        started = time.time()
        reply = plan.reply([{'direction': 'in', 'kind': 'text', 'text': text}], [], [],
                           chat_context={}, search_fn=search_fn)
        print('  回复:', reply[:140])
        print('  整条耗时: %.2fs' % (time.time() - started))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
