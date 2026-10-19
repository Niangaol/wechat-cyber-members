"""隔离跑 v4_service.py 里的单个探针（不执行模块底部的整套 runner）。

用法： python3 verify_qq/_isolate.py t_context_only_still_recorded [次数]
       python3 verify_qq/_isolate.py t_stop_during_generation t_context_only_still_recorded
"""
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / 'src'))

source = (HERE / 'v4_service.py').read_text(encoding='utf-8')
head = source.split("\ngroup('§6/§7", 1)[0]          # 砍掉底部的整套运行器
mod = types.ModuleType('v4_isolated')
mod.__file__ = str(HERE / 'v4_service.py')
exec(compile(head, str(HERE / 'v4_service.py'), 'exec'), mod.__dict__)

names = sys.argv[1:]
if not names:
    print('用法：python3 verify_qq/_isolate.py <探针名> [<探针名> ...]')
    raise SystemExit(2)

fails = 0
for name in names:
    fn = getattr(mod, name, None)
    if fn is None:
        print('没有这个探针：%s' % name)
        continue
    print('=== %s ===' % name)
    try:
        fn()
    except AssertionError as exc:
        fails += 1
        print('  AssertionError: %s' % str(exc)[:300])
    except Exception as exc:                       # noqa: BLE001
        fails += 1
        print('  %s: %s' % (type(exc).__name__, str(exc)[:300]))
print('失败探针数：%d' % fails)
