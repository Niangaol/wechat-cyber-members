"""对抗式验证 7：静态扫描现有测试的"弱断言"。

判定规则（都是"能骗过评审"的常见写法）：
A. 只断言 reason，从不断言 action —— action 才是行为，reason 只是文案；
B. 只断言 action，从不断言 priority —— 优先级错了（@ 被降级）看不出来；
C. 测试方法里没有任何断言（只调用了被测代码）；
D. 断言里出现 "or True" / "if False" / 恒真表达式；
E. 断言用 assertTrue(x) 而 x 明显是恒真/恒假量。

运行：python3 verify_qq/v7_weak_tests.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ['test_qq_core.py', 'test_qq_core_policy.py', 'test_qq_plugin.py',
         'test_qq_deploy.py', 'test_qq_shared_state.py']
ASSERT_PREFIX = 'assert'


def src_of(node, lines):
    return ast.get_source_segment('\n'.join(lines), node) or ''


def collect_asserts(func):
    out = []
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr.startswith(ASSERT_PREFIX):
            out.append(node)
        elif isinstance(node, ast.Assert):
            out.append(node)
    return out


def main():
    findings = {'A': [], 'B': [], 'C': [], 'D': []}
    counts = {'tests': 0, 'asserts': 0}
    for name in FILES:
        path = ROOT / name
        if not path.is_file():
            continue
        lines = path.read_text(encoding='utf-8').splitlines()
        tree = ast.parse('\n'.join(lines))
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
                if not fn.name.startswith('test'):
                    continue
                counts['tests'] += 1
                asserts = collect_asserts(fn)
                counts['asserts'] += len(asserts)
                texts = [src_of(a, lines) for a in asserts]
                blob = '\n'.join(texts)
                if not texts:
                    findings['C'].append('%s::%s' % (cls.name, fn.name))
                    continue
                uses_reason = '.reason' in blob or "'reason'" in blob
                uses_action = '.action' in blob or "'action'" in blob
                uses_prio = '.priority' in blob or "'priority'" in blob
                if uses_reason and not uses_action:
                    findings['A'].append('%s::%s' % (cls.name, fn.name))
                if uses_action and not uses_prio and 'PRIORITY' not in blob:
                    findings['B'].append('%s::%s' % (cls.name, fn.name))
                for t in texts:
                    if 'or True' in t or 'if False' in t or 'assertTrue(True' in t:
                        findings['D'].append('%s::%s  %s' % (cls.name, fn.name, t[:90]))

    print('扫描 %d 个测试文件：%d 个测试方法，%d 条断言'
          % (len(FILES), counts['tests'], counts['asserts']))
    print()
    print('A. 只断言 reason、从不断言 action（reason 是文案，action 才是行为）：')
    for item in findings['A']:
        print('   ', item)
    print('   小计 %d' % len(findings['A']))
    print()
    print('B. 只断言 action、从不断言 priority（@ 被降级成普通优先级看不出来）：')
    for item in findings['B']:
        print('   ', item)
    print('   小计 %d' % len(findings['B']))
    print()
    print('C. 没有任何断言的测试方法：')
    for item in findings['C']:
        print('   ', item)
    print('   小计 %d' % len(findings['C']))
    print()
    print('D. 断言里出现恒真/可疑表达式：')
    for item in findings['D']:
        print('   ', item)
    print('   小计 %d' % len(findings['D']))
    print()
    print('说明：A/B 是"提示"不是"错误"——很多用例确实只在验证某一维度。'
          '真正的问题是**整条规则**没有任何一处断言优先级/动作。')


if __name__ == '__main__':
    main()
