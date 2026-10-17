#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
python3 - <<'PY'
import sys, time
sys.path.insert(0, 'src')
from imagegen import generate, oc_prefix, OC_REF, ImageGenError

prompt = oc_prefix() + "。场景：年糕站在春天的樱花树下，抬头看飘落的花瓣，伸手接住一片。"
print("PROMPT_LEN:", len(prompt))
print("--- 带参考图生成 ---")
t0 = time.time()
try:
    p = generate(prompt, ref_image=OC_REF)
    print("GEN_OK_WITH_REF", p, p.stat().st_size, "bytes", round(time.time()-t0,1), "s")
except Exception as e:
    print("GEN_FAIL_WITH_REF", type(e).__name__, str(e)[:300])
    print("--- 退回纯文字生成 ---")
    try:
        p = generate(prompt)
        print("GEN_OK_TEXT_ONLY", p, p.stat().st_size, "bytes")
    except Exception as e2:
        print("GEN_FAIL_TEXT_ONLY", type(e2).__name__, str(e2)[:200])
PY
