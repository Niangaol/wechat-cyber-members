#!/usr/bin/env python3
"""实测新的云端模型端点（默认读 config/resident.json 的 model 块，并强制启用）。

只做模型调用，**不碰微信界面**，随时可安全运行：
    wsl.exe -d Ubuntu-24.04 -u niangao -e bash -lc 'cd /mnt/d/AgentPrograms/wechat-bot && python3 wsl/check-model.py'

检查：密钥是否就位 → 文本一次 → 真实 usage → max_tokens 截断行为 → 图片输入（data URL）→ 错误分类。
不打印密钥；退出码 0 = 全部通过。
"""
import base64, io, json, sys, time
from pathlib import Path

ROOT = "/mnt/d/AgentPrograms/wechat-bot"
sys.path[:0] = [ROOT, ROOT + "/src"]
from PIL import Image                                       # noqa: E402
from model_api import ModelProvider, resolve_providers, ModelUnavailable, ModelAuthError  # noqa: E402

cfg = json.loads(Path(ROOT + "/config/resident.json").read_text())
# 测**当前生效**的 provider，而不是强制启用某个块：
# 现在两种形态都合法（模型块启用 → OpenCode Go；model.enabled=false → 回 StepFun StepPlan），
# 冒烟测试必须跟着当前配置走，否则会出现"测的和跑的不是一个东西"。
p = resolve_providers(cfg)
main, ocr = p["main"], p["ocr"]
if not main.key():
    print("当前 provider 没有密钥（%s）" % main.model)
    sys.exit(3)
results = []


def step(name, fn):
    t0 = time.time()
    try:
        detail = fn() or ""
        results.append((True, name, "%s (%.1fs)" % (detail, time.time() - t0)))
    except Exception as exc:                                # noqa: BLE001
        results.append((False, name, "%s: %s" % (type(exc).__name__, str(exc)[:120])))


print("main =", main.base_url, main.model, "| ocr =", (ocr.base_url + " " + ocr.model) if ocr else None)
print("密钥:", "已就位" if not main.needs_key() else "缺失（先按 OPERATIONS 写凭据，别粘到对话里）")
if main.needs_key():
    sys.exit(3)

def _truncation_probe(provider):
    """把 max_tokens 压到很小，观察是报错（被当作失败）还是静默返回半句。"""
    try:
        text = provider.chat([{"role": "user", "content": "请写一段 200 字的自我介绍"}], 8)[0]
        return "未触发截断（返回 %d 字）——正式使用前要人工确认这是预期的" % len(text)
    except ModelUnavailable as exc:
        return "截断被正确识别为失败：%s" % str(exc)[:60]


def _image_probe(provider):
    """图片输入：用 OC 参考图缩到 384px 走 data URL，看模型能不能说出画面内容。"""
    src = Path(ROOT) / "config" / "assets" / "oc-reference.png"
    if not src.exists():
        return "跳过（没有 %s）" % src
    img = Image.open(src).convert("RGB")
    img.thumbnail((384, 384))
    buf = io.BytesIO(); img.save(buf, "PNG")
    url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    text = provider.chat([{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": url}},
        {"type": "text", "text": "一句话描述这张图里有什么。"}]}], 600)[0]
    return "模型描述=%r" % text[:60]


# 预算别抠：推理模型（step-5 / MiMo / LongCat）会先把思考写进 completion，
# max_tokens=32 这种小额度会被思考吃光、finish_reason=length，看起来像"模型坏了"。
step("文本调用", lambda: "回复=%r" % main.chat(
    [{"role": "user", "content": "只回两个字：收到"}], 400)[0][:20])

step("真实 usage", lambda: "tokens=%s" % (
    main.chat([{"role": "user", "content": "数一下：一二三"}], 400)[1].get("total_tokens")))

step("max_tokens 截断处理", lambda: _truncation_probe(main))

step("图片输入(data URL)", lambda: _image_probe(main))

print("=" * 78)
for ok, name, detail in results:
    print("%s  %-22s %s" % ("✅" if ok else "❌", name, detail))
print("=" * 78)
bad = [n for ok, n, _ in results if not ok]
print("总计 %d 项，失败 %d 项%s" % (len(results), len(bad), ("：" + ", ".join(bad)) if bad else "（全部通过）"))
sys.exit(1 if bad else 0)
