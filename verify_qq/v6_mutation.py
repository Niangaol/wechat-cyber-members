"""对抗式验证 6：突变测试——"能不能骗过现有测试"。

做法：把 qq/ 与测试文件复制到 verify_qq/mutations/<编号>/（src/ 用符号链接指回真实目录，
只读），在**副本**里注入一个语义错误，再跑现有测试。
- 测试失败 → 突变被杀死（说明这条规则真的被测到了）；
- 测试仍全绿 → 突变存活（说明现有测试覆盖不到这个行为，是**测试缺口**）。

绝不修改仓库里的 qq/**、src/**、test_**：所有改动都只发生在 verify_qq/ 下的副本里。

运行：python3 verify_qq/v6_mutation.py            # 全部
      python3 verify_qq/v6_mutation.py M05        # 只跑一个
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).resolve().parent / 'mutations'
MODULES = ['test_qq_core', 'test_qq_core_policy', 'test_qq_plugin',
           'test_qq_shared_state']

# (编号, 一句话说明, 文件, 原文, 替换)
MUTATIONS = [
    ('M01', '@全体 被当成 @我', 'qq/core/envelope.py',
     "            if target == 'all':\n                at_all = True\n",
     "            if target == 'all':\n                at_all = True\n                at_me = True\n"),
    ('M02', '不再丢弃"自己发的消息"', 'qq/core/envelope.py',
     "    if not sender_id or sender_id == self_id:\n        return None",
     "    if not sender_id:\n        return None"),
    ('M03', 'message_id 缺失也放行（去重键会撞）', 'qq/core/envelope.py',
     "    if not message_id:\n        return None",
     "    if not message_id and False:\n        return None"),
    ('M04', 'dedupe_key 去掉 self_id（跨账号撞键）', 'qq/core/envelope.py',
     "        return '%s:%s:%s:%s' % (self.self_id, self.chat_type, self.chat_id,\n                                self.message_id)",
     "        return '%s:%s:%s' % (self.chat_type, self.chat_id, self.message_id)"),
    ('M05', '未登记的群也回话（白名单失效）', 'qq/core/policy.py',
     "    if entry is None:\n        # 未登记的群一律 ignore：不记时间线、不花额度、绝不回话。\n        return Decision('ignore', PRIORITY_GROUP_PLAIN, 'group_not_registered')",
     "    if entry is None:\n        return Decision('reply', PRIORITY_GROUP_AT, 'group_not_registered')"),
    ('M06', '配置类型不对时 fail-OPEN（改成 reply）', 'qq/core/policy.py',
     "        return Decision('ignore', PRIORITY_GROUP_PLAIN, 'bad_config:%s' % exc)",
     "        return Decision('reply', PRIORITY_GROUP_AT, 'bad_config:%s' % exc)"),
    ('M07', 'plain_mode 默认改成 all（最宽松）', 'qq/core/policy.py',
     "DEFAULT_PLAIN_MODE = 'at_only'", "DEFAULT_PLAIN_MODE = 'all'"),
    ('M08', '别名命中降级成普通优先级', 'qq/core/policy.py',
     "        return Decision('reply', PRIORITY_GROUP_AT, 'mention_alias')",
     "        return Decision('reply', PRIORITY_GROUP_PLAIN, 'mention_alias')"),
    ('M09', '去掉 min_reply_seconds 频率闸', 'qq/core/policy.py',
     "            if gate > 0 and last_reply_at and (float(now) - float(last_reply_at)) < gate:",
     "            if False:"),
    ('M10', '私聊黑名单失效', 'qq/core/policy.py',
     "        if chat_id in _id_set(cfg, 'direct_blacklist'):", "        if False:"),
    ('M11', '去掉像素上限（解压炸弹放行）', 'qq/core/media.py',
     "    if width * height > MAX_PIXELS:", "    if False:"),
    ('M12', '去掉端口白名单', 'qq/core/media.py',
     "        if port not in ALLOWED_PORTS:\n            raise MediaError('禁止非标准端口')",
     "        if False:\n            raise MediaError('禁止非标准端口')"),
    ('M13', '失败时把异常抛给调用方（不再返回 None）', 'qq/core/media.py',
     "    except (MediaError, WebSafetyError) as exc:\n        logging.warning(",
     "    except (MediaError, WebSafetyError) as exc:\n        raise\n    except Exception as _never:\n        logging.warning("),
    ('M14', 'seen() 永不去重（同一条消息回两遍）', 'qq/core/store.py',
     "        return cursor.rowcount == 1", "        return True"),
    ('M15', 'auto_send=false 也照样发送', 'qq/core/worker.py',
     "        if not self.service.auto_send:", "        if False:"),
    ('M16', 'STOP 文件不再拦住发送', 'qq/core/worker.py',
     "        if self.service.any_stop():\n            logging.info('qq_stop_skip chat=%s reason=stop_file', chat_key)",
     "        if False:\n            logging.info('qq_stop_skip chat=%s reason=stop_file', chat_key)"),
    ('M17', '跳过输出安全闸（超长原文直发）', 'qq/core/worker.py',
     "        return check_output(reply, service.reply_max_chars)",
     "        return reply"),
    ('M18', 'unknown（结果未知）记成 ok 台账', 'qq/core/worker.py',
     "            self.service.store.record_send(chat_key, 'text', 'unknown',",
     "            self.service.store.record_send(chat_key, 'text', 'ok',"),
    ('M19', 'queue_full 闸失效（队列无限增长）', 'qq/core/service.py',
     "            if self.quota.depth() >= self.max_queue:", "            if False:"),
    ('M20', '跳过任务保鲜期（深夜的活第二天早上还回）', 'qq/core/worker.py',
     "        if ttl > 0 and age > ttl:", "        if False:"),
    # ↓ 专门针对"只断言 reason、只断言 action"的盲区设计
    ('M21', '普通回复全变成 context_only（reason 不变）', 'qq/core/policy.py',
     "    if reply:\n        return Decision('reply', PRIORITY_GROUP_PLAIN, reason)",
     "    if False:\n        return Decision('reply', PRIORITY_GROUP_PLAIN, reason)"),
    ('M22', '真 @ 的优先级被降级成普通（action 不变）', 'qq/core/policy.py',
     "        return Decision('reply', PRIORITY_GROUP_AT, 'at_me')",
     "        return Decision('reply', PRIORITY_GROUP_PLAIN, 'at_me')"),
    ('M23', '追问命中降级成普通优先级（action 不变）', 'qq/core/policy.py',
     "        return Decision('reply', PRIORITY_GROUP_AT, 'followup_question')",
     "        return Decision('reply', PRIORITY_GROUP_PLAIN, 'followup_question')"),
    ('M24', 'plain_per_hour 上限失效（每小时不限量）', 'qq/core/policy.py',
     "        if cap > 0 and count >= cap:", "        if False:"),
    ('M25', 'idle 模式的队列忙判定失效（把别人的 @ 挤后面）', 'qq/core/policy.py',
     "        if int(queue_depth or 0) > 0:", "        if False:"),
]


def prepare(mid):
    target = BASE / mid
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copytree(ROOT / 'qq', target / 'qq',
                    ignore=shutil.ignore_patterns('__pycache__'))
    (target / 'src').symlink_to(ROOT / 'src', target_is_directory=True)
    for name in MODULES:
        shutil.copy2(ROOT / (name + '.py'), target / (name + '.py'))
    return target


def apply_mutation(target, path, old, new):
    file = target / path
    text = file.read_text(encoding='utf-8')
    if old not in text:
        return False, '原文没找到（实现已改动？）'
    file.write_text(text.replace(old, new, 1), encoding='utf-8')
    return True, ''


FLAKY = 'test_status_has_contract_fields_and_is_written_atomically'


def run_tests(target, timeout=180):
    """→ (returncode, 失败用例名集合, 输出尾部)

    注意：test_qq_core 里那个原子写用例本身是 flaky 的（实测单跑 25 次挂 5 次，
    原因是后台心跳线程与断言之间抢 .status.json.*.tmp 的存在窗口）。
    所以判定"突变是否被杀死"不能只看 returncode，要比**失败用例集合**，
    并且把已知 flaky 的那个从集合里剔掉。
    """
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    proc = subprocess.run([sys.executable, '-m', 'unittest'] + MODULES,
                          cwd=str(target), capture_output=True, text=True,
                          timeout=timeout, env=env)
    text = (proc.stderr or '') + (proc.stdout or '')
    names = set()
    for line in text.splitlines():
        if line.startswith(('FAIL: ', 'ERROR: ')):
            parts = line.split()
            if len(parts) > 1:
                names.add(parts[1])
    names.discard(FLAKY)
    return proc.returncode, names, text[-400:]


def baseline_failures(base_dir, tries=4):
    """基线必须真的绿（剔除已知 flaky 之后）。返回基线失败集合。"""
    for attempt in range(1, tries + 1):
        rc, names, tail = run_tests(base_dir)
        if not names:
            print('  基线第 %d 次：绿（剔除已知 flaky 后无失败）' % attempt)
            return names
        print('  基线第 %d 次仍红：%s' % (attempt, sorted(names)))
    print('  基线连续 %d 次都红，突变结论不可信，退出' % tries)
    return None


def main():
    only = sys.argv[1:] or None
    BASE.mkdir(parents=True, exist_ok=True)
    killed, survived, broken = [], [], []
    print('基线：先在未突变的副本里跑一遍（必须全绿，否则突变结论不可信）')
    base_dir = prepare('_baseline')
    base_fail = baseline_failures(base_dir)
    if base_fail is None:
        return 2
    print()

    for mid, desc, path, old, new in MUTATIONS:
        if only and mid not in only:
            continue
        target = prepare(mid)
        ok, why = apply_mutation(target, path, old, new)
        if not ok:
            print('%-5s %-34s SKIP  %s' % (mid, desc, why))
            broken.append((mid, desc, why))
            continue
        started = time.time()
        try:
            rc, names, tail = run_tests(target)
        except subprocess.TimeoutExpired:
            print('%-5s %-34s TIMEOUT' % (mid, desc))
            broken.append((mid, desc, '超时'))
            continue
        spent = time.time() - started
        new_failures = names - base_fail
        if new_failures:
            sample = sorted(new_failures)[0]
            killed.append((mid, desc, sample))
            print('%-5s %-34s 杀死（%d 个用例变红）%.0fs  例：%s'
                  % (mid, desc, len(new_failures), spent, sample))
        else:
            survived.append((mid, desc))
            print('%-5s %-34s *** 存活（无新增失败）*** %.0fs' % (mid, desc, spent))

    print()
    print('=' * 74)
    print('突变测试结果：共 %d 个突变，杀死 %d，存活 %d，未能应用 %d'
          % (len(killed) + len(survived) + len(broken), len(killed),
             len(survived), len(broken)))
    if survived:
        print()
        print('!! 现有测试**覆盖不到**的行为（突变存活 = 测试缺口）：')
        for mid, desc in survived:
            print('   %-5s %s' % (mid, desc))
    print('=' * 74)
    return 0


if __name__ == '__main__':
    sys.exit(main())
