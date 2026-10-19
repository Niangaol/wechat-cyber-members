"""极简断言框架：只打印 PASS/FAIL 与真实观测值，末尾汇总，失败则退出码 1。"""
import sys
import traceback

_RESULTS = []
_GROUP = ['']


def group(name):
    _GROUP[0] = name
    print('')
    print('=== %s ===' % name)


def check(name, ok, detail=''):
    detail = '' if detail == '' else str(detail)
    _RESULTS.append((_GROUP[0], name, bool(ok)))
    print('  [%s] %s%s' % ('PASS' if ok else 'FAIL', name,
                           ('   <- ' + detail) if detail else ''))
    return bool(ok)


def observe(name, ok, detail=''):
    """观察项：不符合契约硬性要求、但值得报告的健壮性缺口；不影响退出码。"""
    _RESULTS.append((_GROUP[0], name, True))
    print('  [OBSERVE] %s%s' % (name, ('   <- ' + detail) if detail else ''))
    return bool(ok)


def eq(name, got, want):
    return check(name, got == want, 'got=%r want=%r' % (got, want))


def run(fn, name=None):
    """跑一个探针函数；抛异常记成 FAIL 而不是中断整份报告。"""
    label = name or getattr(fn, '__name__', 'probe')
    try:
        fn()
    except Exception as exc:
        _RESULTS.append((_GROUP[0], label, False))
        print('  [FAIL] %s 抛出异常 %s: %s' % (label, type(exc).__name__, exc))
        traceback.print_exc()


def summary(title):
    failed = [r for r in _RESULTS if not r[2]]
    print('')
    print('=' * 62)
    print('%s：共 %d 项，PASS %d，FAIL %d'
          % (title, len(_RESULTS), len(_RESULTS) - len(failed), len(failed)))
    for grp, name, _ in failed:
        print('  FAIL  [%s] %s' % (grp, name))
    print('=' * 62)
    sys.exit(1 if failed else 0)
