"""量一下每次回复的提示词有多大（不调模型）：看有没有该瘦的地方。"""
import sys, json, os, sqlite3
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from memory import ChatMemory
from search import HotFeed

db = sqlite3.connect(os.path.expanduser("~/.local/state/wechat-bot/ledger.sqlite"))
mem = ChatMemory(db)
feed = HotFeed(db)
for ck in ("group:Agent 聊天测试群", "direct:很帅的年糕"):
    ctx = mem.context_for(ck)
    hist = ctx.get('recent_turns', [])
    tl = ctx.get('timeline', [])
    hot = feed.relevant('最近有什么热搜')
    payload = {
        'history': hist[-12:],
        'new_messages': [{'direction': 'in', 'kind': 'text', 'text': '测试消息' * 3}],
        'web_sources_untrusted': [],
        'timeline_text': [{'direction': t['direction'], 'kind': t['kind'], 'text': t['text'][:200]}
                          for t in tl[-20:]],
    }
    body = json.dumps(payload, ensure_ascii=False)
    style = str(ctx.get('style', ''))
    facts = ctx.get('facts') or []
    print("%-32s history=%d timeline=%d style=%d facts=%d hot=%d" % (
        ck, len(hist), len(tl), len(style), len(facts), len(hot)))
    print("    payload chars=%d  (timeline_text=%d, history=%d)" % (
        len(body), len(json.dumps(payload['timeline_text'], ensure_ascii=False)),
        len(json.dumps(payload['history'], ensure_ascii=False))))
    print("    system 附加：style %d + facts %d + hot %d chars" % (
        len(style), sum(len(str(f)) for f in facts),
        sum(len(str(h.get('title', ''))) for h in hot[:8])))
