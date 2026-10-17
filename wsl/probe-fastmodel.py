"""对比：把回复模型换成 step-3.7-flash（OCR 那个小模型）会不会又快又够用。"""
import json, sqlite3, sys, time
from pathlib import Path
ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from multimodal import StepPlan                       # noqa: E402

base = json.loads(Path(ROOT + "/config/resident.json").read_text())
cases = [
    ("群里被 @", [{"direction": "in", "kind": "text", "text": "@年糕 今天杭州热死了，你热吗", "at_me": 1}]),
    ("普通闲聊", [{"direction": "in", "kind": "text", "text": "中午吃啥好", "at_me": 0}]),
]
for model in ("step-3.7-flash", "step-5-preview"):
    plan_cfg = dict(base, step_plan=dict(base["step_plan"], model=model, reasoning_effort=None))
    plan = StepPlan(plan_cfg, sqlite3.connect(":memory:"))
    print("=== %s (effort=%s) ===" % (model, plan.main.reasoning_effort))
    for name, msgs in cases:
        t0 = time.time()
        try:
            reply = plan.reply(msgs, [], [], chat_context={"style": "", "facts": [], "timeline": []})
            print("   %-8s %5.1fs  %r" % (name, time.time() - t0, reply[:70]))
        except Exception as exc:                      # noqa: BLE001
            print("   %-8s %5.1fs  FAILED %s: %s" % (name, time.time() - t0, type(exc).__name__, str(exc)[:90]))