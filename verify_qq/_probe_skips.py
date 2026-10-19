"""列出 test_qq_core 里到底哪些用例被跳过、哪些类真的跑了。"""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import test_qq_core as m

loader = unittest.TestLoader()
suite = loader.loadTestsFromModule(m)
skipped, ran = [], {}


def walk(s):
    for item in s:
        if isinstance(item, unittest.TestSuite):
            walk(item)
        else:
            yield_one(item)


def yield_one(case):
    cls = type(case).__name__
    ran[cls] = ran.get(cls, 0) + 1
    result = unittest.TestResult()
    case.run(result)
    if result.skipped:
        skipped.append((cls, case._testMethodName, result.skipped[0][1]))
    elif not result.wasSuccessful():
        print('FAILED:', cls, case._testMethodName, result.errors, result.failures)


for case in walk(suite):
    pass

print('实际收集到的用例数：', sum(ran.values()))
print()
print('被跳过的用例（%d）：' % len(skipped))
for cls, name, why in skipped:
    print('  %-24s %-52s %s' % (cls, name, str(why).splitlines()[0][:80]))
print()
print('每个类实际跑到的用例数：')
for cls in sorted(ran):
    print('  %-28s %d' % (cls, ran[cls]))
