"""私聊开关：direct_enabled=false 时完全不看私聊（用户 2026-10-17 决定只做群聊）。"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from resident import Resident                                  # noqa: E402


def resident():
    return Resident.__new__(Resident)


BASE = {
    'target_chat': '很帅的年糕',
    'direct_whitelist': ['很帅的年糕', 'Deepseek'],
    'watch_chats': ['Agent 聊天测试群', '人机'],
    'group_whitelist': ['Agent 聊天测试群', '人机'],
}


class DirectOffTests(unittest.TestCase):
    def test_disabled_skips_every_direct_chat(self):
        cfg = dict(BASE, direct_enabled=False)
        names = resident().watch_list(cfg)
        self.assertEqual(names, ['Agent 聊天测试群', '人机'])
        self.assertNotIn('很帅的年糕', names)
        self.assertNotIn('Deepseek', names)

    def test_enabled_still_watches_registered_directs(self):
        cfg = dict(BASE, direct_enabled=True)
        names = resident().watch_list(cfg)
        self.assertIn('很帅的年糕', names)
        self.assertIn('Deepseek', names)
        self.assertIn('人机', names)

    def test_default_is_enabled_for_backward_compat(self):
        """没写这个键的老配置行为不变（不会被静默改成"只看群"）。"""
        names = resident().watch_list(dict(BASE))
        self.assertIn('很帅的年糕', names)

class GroupFirstTests(unittest.TestCase):
    """「以群聊为主」的硬保证：私信轮到自己时，如果队列里还有群 @ 在等，就让位。

    用户 2026-10-17 要求：私聊加回来，但以群聊消息为主。队列本身已按
    群@(0) > 私信(1) > 群普通(2) 排序，这里再加一道「已经在跑的私信也要让路」。
    """

    def make(self, top_priority):
        r = resident()
        seen = {"finished": [], "enqueued": []}

        class Q:
            def claim(self):
                return (7, "direct:很帅的年糕", 1, 0.0,
                        json.dumps({"messages": [{"direction": "in", "text": "hi"}]}))

            def peek(self):
                return (9, "group:人机", top_priority, 0.0, "{}")

            def finish(self, qid, state):
                seen["finished"].append((qid, state))

            def enqueue(self, ck, priority, payload):
                seen["enqueued"].append((ck, priority, json.loads(payload).get("yield_count")))

        r.quota = Q()
        r.stop = type("S", (), {"exists": lambda self: False})()
        r.status = lambda *a, **k: None
        return r, seen

    def test_direct_yields_when_group_task_waiting(self):
        r, seen = self.make(0)                     # 队列里有群 @（优先级 0）
        self.assertFalse(r.process_queue({}, None, None))
        self.assertEqual(seen["finished"], [(7, "YIELDED_FOR_GROUP")])
        self.assertEqual(seen["enqueued"], [("direct:很帅的年糕", 1, 1)])

    def test_direct_does_not_yield_to_plain_group_chatter(self):
        """群里只有普通闲聊在等时不值得让位——私信还是优先于群闲聊。"""
        r, seen = self.make(2)
        try:
            r.process_queue({}, None, None)
        except Exception:                          # noqa: BLE001 后面 ui=None 必然失败，这里不关心
            pass
        states = [s for _, s in seen["finished"]]
        self.assertNotIn("YIELDED_FOR_GROUP", states, "只该让位给群 @，不该让给群闲聊")

    def test_yield_is_capped(self):
        """让位最多 3 次，避免和别的会话互相踢皮球把消息饿死。"""
        r, seen = self.make(0)
        r.quota.claim = lambda: (7, "direct:很帅的年糕", 1, 0.0,
                                 json.dumps({"messages": [], "yield_count": 3}))
        try:
            r.process_queue({}, None, None)
        except Exception:                          # noqa: BLE001
            pass
        states = [s for _, s in seen["finished"]]
        self.assertNotIn("YIELDED_FOR_GROUP", states, "让位最多 3 次，第 4 次必须照发")

if __name__ == '__main__':
    unittest.main()
