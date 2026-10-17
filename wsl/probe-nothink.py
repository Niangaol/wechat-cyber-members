"""试试 step-5-preview 能不能"无思考"：none / minimal / 不传 / low 四种，看延迟和 reasoning 长度。"""
import json, sys, time, urllib.request, urllib.error
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from model_api import load_credentials                  # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
sp = cfg["step_plan"]
key = (load_credentials() or {}).get("step_plan_api_key") or ""
if not key:
    print("没找到 step_plan_api_key"); sys.exit(3)
url = sp["base_url"].rstrip("/") + "/chat/completions"

def call(effort):
    body = {"model": sp["model"], "max_tokens": 300, "stream": False,
            "messages": [{"role": "user", "content": "只回两个字：收到"}]}
    if effort is not None:
        body["reasoning_effort"] = effort
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json",
                                          "User-Agent": "niangao-wechat-agent/1.0"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read(2 * 1024 * 1024))
    except urllib.error.HTTPError as exc:
        return "HTTP %s %s" % (exc.code, exc.read()[:160].decode("utf-8", "replace"))
    except Exception as exc:                             # noqa: BLE001
        return "%s: %s" % (type(exc).__name__, str(exc)[:120])
    ms = int((time.time() - t0) * 1000)
    msg = ((data.get("choices") or [{}])[0].get("message") or {})
    reasoning = str(msg.get("reasoning_content") or msg.get("reasoning") or "")
    return "%5dms reasoning=%3d字 content=%r" % (ms, len(reasoning), str(msg.get("content"))[:20])

for effort in ("none", "minimal", None, "low"):
    print("%-9s -> %s" % (str(effort), call(effort)))