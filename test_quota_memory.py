import json, sqlite3, sys, time, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent/'src'))
from quota import (Quota, QuotaExceeded, PRIORITY_GROUP_AT, PRIORITY_DIRECT,
                   PRIORITY_GROUP_PLAIN, merge_payloads, MERGE_LIMIT)
from memory import ChatMemory, LEARN_EVERY

class QueueMergeTests(unittest.TestCase):
    """排队期间滚出视口的消息不能丢：合并而不是覆盖（2026-10-17 计划评审点名的风险）。"""

    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.q = Quota(self.db)

    @staticmethod
    def payload(*signatures):
        return json.dumps({'messages': [{'signature': s, 'text': 'msg-' + s} for s in signatures],
                           'want_search': False}, ensure_ascii=False)

    def pending(self):
        row = self.db.execute("SELECT id, payload FROM queue WHERE state='PENDING'").fetchall()
        self.assertEqual(len(row), 1, '同一会话只该有一个待处理任务')
        return json.loads(row[0][1])

    def test_second_enqueue_keeps_first_message(self):
        self.q.enqueue('group:人机', PRIORITY_GROUP_PLAIN, self.payload('a'))
        self.q.enqueue('group:人机', PRIORITY_GROUP_PLAIN, self.payload('b'))
        merged = self.pending()
        self.assertEqual([m['signature'] for m in merged['messages']], ['a', 'b'])

    def test_duplicate_signature_is_deduped(self):
        self.q.enqueue('group:人机', PRIORITY_GROUP_PLAIN, self.payload('a', 'b'))
        self.q.enqueue('group:人机', PRIORITY_GROUP_PLAIN, self.payload('b', 'c'))
        merged = self.pending()
        self.assertEqual([m['signature'] for m in merged['messages']], ['a', 'b', 'c'])

    def test_other_chat_is_not_merged(self):
        self.q.enqueue('group:人机', PRIORITY_GROUP_PLAIN, self.payload('a'))
        self.q.enqueue('group:别的群', PRIORITY_GROUP_PLAIN, self.payload('z'))
        self.assertEqual(self.q.depth(), 2)

    def test_want_search_is_sticky(self):
        self.q.enqueue('group:人机', PRIORITY_GROUP_PLAIN,
                       json.dumps({'messages': [{'signature': 'a'}], 'want_search': True}))
        self.q.enqueue('group:人机', PRIORITY_GROUP_PLAIN, self.payload('b'))
        self.assertTrue(self.pending()['want_search'], '旧的"要热搜"不能因为合并丢掉')

    def test_merge_is_capped_and_reports_trimming(self):
        for i in range(MERGE_LIMIT + 5):
            self.q.enqueue('group:人机', PRIORITY_GROUP_PLAIN, self.payload('s%02d' % i))
        merged = self.pending()
        self.assertEqual(len(merged['messages']), MERGE_LIMIT)
        self.assertEqual(merged['messages'][-1]['signature'], 's%02d' % (MERGE_LIMIT + 4))
        self.assertGreater(merged.get('merge_trimmed', 0), 0, '裁剪了就要如实写出来')


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.q = Quota(self.db)
        self.limits = {'window_5h': 5, 'window_1d': 100}
    def test_consume_counts(self):
        for _ in range(3): self.q.consume(PRIORITY_DIRECT)
        self.assertEqual(self.q.status()['used_5h'], 3)
    def test_5h_limit(self):
        for _ in range(5): self.q.consume(PRIORITY_DIRECT)
        with self.assertRaises(QuotaExceeded): self.q.check(self.limits)
    def test_1d_limit_independent(self):
        limits = {'window_5h': 100, 'window_1d': 5}
        for _ in range(5): self.q.consume(PRIORITY_DIRECT)
        with self.assertRaises(QuotaExceeded): self.q.check(limits)
    def test_old_usage_expires(self):
        self.db.execute('INSERT INTO usage(created,priority) VALUES(?,?)',
                        (time.time()-6*3600, PRIORITY_DIRECT)); self.db.commit()
        self.assertEqual(self.q.count(5*3600), 0)
    def test_priority_order(self):
        self.q.enqueue('g1', PRIORITY_GROUP_PLAIN, '{}')
        self.q.enqueue('g2', PRIORITY_GROUP_AT, '{}')
        self.q.enqueue('d1', PRIORITY_DIRECT, '{}')
        order = []
        for _ in range(3):
            row = self.q.claim()
            order.append(row[1])
            self.q.finish(row[0], 'SENT')
        self.assertEqual(order, ['g2', 'd1', 'g1'])
    def test_claim_excludes_processing(self):
        self.q.enqueue('a', PRIORITY_DIRECT, '{}')
        row = self.q.claim()
        self.assertEqual(row[1], 'a')
        self.assertIsNone(self.q.claim())
    def test_zombie_lease_requeue(self):
        qid = self.q.enqueue('a', PRIORITY_DIRECT, '{}')
        self.q.claim()
        # 模拟崩溃遗留：把任务时间改到租约之外
        self.db.execute('UPDATE queue SET created=created-301 WHERE id=?', (qid,))
        self.db.commit()
        row = self.q.claim()
        self.assertEqual(row[0], qid)
    def test_fifo_within_priority(self):
        self.q.enqueue('a', PRIORITY_DIRECT, '{}')
        time.sleep(0.01)
        self.q.enqueue('b', PRIORITY_DIRECT, '{}')
        self.assertEqual(self.q.peek()[1], 'a')
    def test_same_chat_supersede(self):
        self.q.enqueue('same', PRIORITY_DIRECT, 'old')
        self.q.enqueue('same', PRIORITY_DIRECT, 'new')
        self.assertEqual(self.q.depth(), 1)
    def test_finish_removes(self):
        qid = self.q.enqueue('x', PRIORITY_DIRECT, '{}')
        self.q.finish(qid, 'SENT')
        self.assertEqual(self.q.depth(), 0)

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.m = ChatMemory(self.db)
    def test_profiles_isolated(self):
        self.m.note_messages('direct:年糕', 3, 'direct', '很帅的年糕')
        self.m.note_messages('group:家庭群', 3, 'group', '家庭群')
        self.m.db.execute('UPDATE profiles SET style=? WHERE chat_key=?',
                          ('软萌毒舌', 'direct:年糕')); self.m.db.commit()
        self.assertEqual(self.m.profile('group:家庭群')[2], '')
        self.assertEqual(self.m.profile('direct:年糕')[2], '软萌毒舌')
    def test_needs_learn_threshold(self):
        self.assertFalse(self.m.needs_learn('c'))
        self.m.note_messages('c', LEARN_EVERY)
        self.assertTrue(self.m.needs_learn('c'))
    def test_learn_writes_only_own_chat(self):
        self.m.note_messages('c1', LEARN_EVERY, 'direct')
        self.m.note_messages('c2', 1, 'direct')
        model = type('M', (), {'call': lambda s, m, t: '{"style":"测试风格","facts":["事实A"]}'})()
        self.assertTrue(self.m.learn('c1', [{'direction': 'in', 'kind': 'text', 'text': '你好'}], model))
        self.assertFalse(self.m.needs_learn('c1'))
        ctx1, ctx2 = self.m.context_for('c1'), self.m.context_for('c2')
        self.assertEqual(ctx1['style'], '测试风格')
        self.assertEqual(ctx1['facts'], ['事实A'])
        self.assertEqual(ctx2['style'], '')
        self.assertEqual(ctx2['facts'], [])
    def test_learn_failure_keeps_state(self):
        self.m.note_messages('c', LEARN_EVERY, 'direct')
        model = type('M', (), {'call': lambda s, m, t: (_ for _ in ()).throw(RuntimeError('boom'))})()
        self.assertFalse(self.m.learn('c', [], model))
        self.assertTrue(self.m.needs_learn('c'))
    def test_turns_capped(self):
        for i in range(60): self.m.record_turn('c', 'user', str(i))
        self.assertEqual(len(self.m.context_for('c')['recent_turns']), 12)
    def test_clear_forgets(self):
        self.m.record_turn('c', 'user', 'x')
        self.m.clear('c')
        self.assertEqual(self.m.context_for('c')['recent_turns'], [])

if __name__ == '__main__':
    unittest.main(verbosity=2)
