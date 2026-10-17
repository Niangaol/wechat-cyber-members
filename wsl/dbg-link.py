"""实机验证：链接正文抓取（真联网，仅读）。"""
import sys, json
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from pathlib import Path
from web_reader import fetch_public_text

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text()).get("links", {})
for url in ["https://www.ruanyifeng.com/blog/2024/01/weekly-issue-286.html"]:
    try:
        out = fetch_public_text(url, cfg)
        txt = out.get("untrusted_text", "")
        print("status:", out.get("status"), "chars:", len(txt))
        print("head:", txt.replace("\n", " ")[:110])
    except Exception as exc:
        print("FAILED", type(exc).__name__, str(exc)[:90])
