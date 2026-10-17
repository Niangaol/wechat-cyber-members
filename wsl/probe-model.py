"""探针：看 MiMo-V2.6-Flash 在 Go 端点的响应结构（含 reasoning / usage / 各类 max_tokens 行为）。

只调模型，不碰微信。不打印密钥。用法：python3 wsl/probe-model.py
"""
import json, sys, time, urllib.request
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from model_api import ModelProvider                     # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
block = dict(cfg["model"]); block["enabled"] = True
# 可以临时换模型/思考档位做对比：python3 wsl/probe-model.py <model> [effort]
if len(sys.argv) > 1:
    block["model"] = sys.argv[1]
if len(sys.argv) > 2:
    block["reasoning_effort"] = None if sys.argv[2] == "none" else sys.argv[2]
p = ModelProvider(block, "probe")
print("probe:", p.model, "| reasoning_effort:", p.reasoning_effort)
key = p.key()
if not key:
    print("没有密钥"); sys.exit(3)


def raw(messages, max_tokens, extra=None):
    payload = {"model": p.model, "messages": messages, "max_tokens": max_tokens, "stream": False}
    payload.update(extra or {})
    req = urllib.request.Request(p.base_url + "/chat/completions",
                                 json.dumps(payload, ensure_ascii=False).encode(),
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json",
                                          "User-Agent": p.app_user_agent,
                                          p.session_header: p.instance_session()})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read(4 * 1024 * 1024)
    ms = (time.time() - t0) * 1000
    body = json.loads(data)
    choice = (body.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    return {"ms": int(ms), "finish": choice.get("finish_reason"),
            "content": (msg.get("content") or "")[:60],
            "has_reasoning_field": any(k for k in msg if "reason" in k.lower()),
            "msg_keys": sorted(msg.keys()),
            "reasoning_len": len(str(msg.get("reasoning_content") or msg.get("reasoning") or "")),
            "usage": body.get("usage")}


msg = [{"role": "user", "content": "只回两个字：收到"}]
for mt in (32, 200, 800):
    try:
        print("max_tokens=%-4d %s" % (mt, json.dumps(raw(msg, mt), ensure_ascii=False)[:220]))
    except Exception as exc:                            # noqa: BLE001
        print("max_tokens=%-4d FAILED %s: %s" % (mt, type(exc).__name__, str(exc)[:100]))

print("--- 试 reasoning_effort ---")
for effort in ("low", "none"):
    try:
        print("reasoning_effort=%-5s %s" % (effort, json.dumps(raw(msg, 200, {"reasoning_effort": effort}), ensure_ascii=False)[:200]))
    except Exception as exc:                            # noqa: BLE001
        print("reasoning_effort=%-5s FAILED %s: %s" % (effort, type(exc).__name__, str(exc)[:120]))
