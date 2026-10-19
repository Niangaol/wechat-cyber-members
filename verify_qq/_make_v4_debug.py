"""生成一份带 decide 探针的 v4 调试副本（只写到 verify_qq/）。"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
src = (HERE / 'v4_service.py').read_text(encoding='utf-8')
head = src.split("\ngroup('§6/§7", 1)[0]
spy = '''
# ---- 调试探针：记录每条 decide 的输入与结论 ----
import qq.core.policy as _p
_orig_decide = _p.decide
def _spy_decide(event, cfg, **kw):
    d = _orig_decide(event, cfg, **kw)
    if event is not None and getattr(event, 'chat_id', '') == '30003':
        print('  [DECIDE] text=%r at_me=%s at_all=%s groups=%r -> %s/%s/%s'
              % (getattr(event, 'text', None), getattr(event, 'at_me', None),
                 getattr(event, 'at_all', None),
                 (cfg.get('groups') if isinstance(cfg, dict) else cfg),
                 d.action, d.priority, d.reason))
    return d
_p.decide = _spy_decide
import qq.core.service as _s
_s.policy.decide = _spy_decide
'''
body = src.split("\ngroup('§6/§7", 1)[1]
(HERE / '_v4_debug.py').write_text(head + spy + "\ngroup('§6/§7" + body, encoding='utf-8')
print('已生成 verify_qq/_v4_debug.py')
