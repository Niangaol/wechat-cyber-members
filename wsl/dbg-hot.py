"""实机验证：RSSHub 热榜抓取 + 链接正文抓取（真联网，仅读）。"""
import sys, sqlite3, os, time, json
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from search import HotFeed
from web_reader import fetch_public_text

db = sqlite3.connect(os.path.expanduser("~/.local/state/wechat-bot/ledger.sqlite"))
feed = HotFeed(db)
t0 = time.time()
ok = feed.refresh(force=True)
print("refresh ok sources:", ok, "elapsed %.1fs" % (time.time() - t0))
for r in db.execute("select source, source_name, count(*), max(fetched) from hot_items group by source"):
    print("   ", r[0], r[1], r[2], time.strftime("%H:%M:%S", time.localtime(r[3])))
print("relevant(热搜):", feed.relevant("最近有什么热搜")[:2])
try:
    txt = fetch_public_text("https://www.ruanyifeng.com/blog/2024/01/weekly-issue-286.html")
    print("link fetch chars:", len(txt or ""), "head:", (txt or "")[:60].replace("\n", " "))
except Exception as exc:
    print("link fetch failed:", type(exc).__name__, exc)
