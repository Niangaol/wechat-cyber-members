"""验证环境自检：确认路径、解释器、可导入的 qq.core 模块（离线）。

用法：python3 verify_qq/_env.py
"""
import sys, os, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

print('python:', sys.version.replace('\n', ' '))
print('root  :', ROOT)
print('verify_qq exists:', (ROOT / 'verify_qq').is_dir())
for mod in ('qq.core.envelope', 'qq.core.policy', 'qq.core.media',
            'qq.core.service', 'qq.core.store', 'qq.core.config', 'qq.core.worker'):
    try:
        __import__(mod)
        print('  import %-22s OK' % mod)
    except Exception as exc:
        print('  import %-22s FAIL %s: %s' % (mod, type(exc).__name__, exc))
try:
    import PIL
    print('Pillow:', PIL.__version__)
except Exception as exc:
    print('Pillow: 不可用', exc)
try:
    import nonebot
    print('nonebot 已安装（注意：core 不该依赖它）')
except Exception as exc:
    print('nonebot: 未安装（预期；qq/core 必须能在无 nonebot 环境跑）')
