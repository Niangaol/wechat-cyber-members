import json, sqlite3, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent/'src'))
from moment_interact import MomentInbox, InteractionPipeline, BATCH_SIZE

class FakeModel:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0
    def call(self, messages, max_tokens=1800):
        self.calls += 1
        return self.replies.pop(0)

class InboxTests(unittest.TestCase):
    def setUp(self):
        self.inbox = MomentInbox(sqlite3.connect(':memory:'))
    def test_add_and_dedup(self):
        self.assertTrue(self.inbox.add('年糕', '今天天气好', False, 'fp1'))
        self.assertFalse(self.inbox.add('年糕', '今天天气好', False, 'fp1'))
        self.assertEqual(self.inbox.pending_count(), 1)
    def test_batch_limit(self):
        for i in range(BATCH_SIZE + 3):
            self.inbox.add('好友%d' % i, '内容%d' % i, False, 'fp%d' % i)
        self.assertEqual(len(self.inbox.pending()), BATCH_SIZE)

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.inbox = MomentInbox(sqlite3.connect(':memory:'))
        for i in range(3):
            self.inbox.add('好友%d' % i, '内容%d' % i, i == 0, 'fp%d' % i)
    def test_run_batch_selective(self):
        model = FakeModel([
            json.dumps([{'id': 1, 'interact': True, 'reason': '可以接梗'},
                        {'id': 2, 'interact': False, 'reason': '广告'},
                        {'id': 3, 'interact': True, 'reason': '真实分享'}], ensure_ascii=False),
            json.dumps([{'id': 1, 'comment': '这块红糖看起来好软！'},
                        {'id': 3, 'comment': '海拉鲁的云也跑这么快吗'}], ensure_ascii=False),
        ])
        stats = InteractionPipeline(model).run_batch(self.inbox)
        self.assertEqual(stats, {'collected': 3, 'selected': 2, 'commented': 2})
        rows = {r[0]: r[1] for r in self.inbox.db.execute('SELECT id,state FROM moment_inbox')}
        self.assertEqual(rows[1], 'READY'); self.assertEqual(rows[2], 'SKIPPED'); self.assertEqual(rows[3], 'READY')
        approved = self.inbox.approved()
        self.assertEqual(len(approved), 2)
        self.assertEqual(approved[0][3], '这块红糖看起来好软！')
    def test_like_comment_bound(self):
        model = FakeModel([
            json.dumps([{'id': 1, 'interact': False, 'reason': '负面'}], ensure_ascii=False),
            json.dumps([], ensure_ascii=False),
        ])
        stats = InteractionPipeline(model).run_batch(self.inbox)
        self.assertEqual(stats['selected'], 0)
        self.assertEqual(self.inbox.approved(), [])
    def test_unsafe_comment_dropped_not_batch(self):
        model = FakeModel([
            json.dumps([{'id': 1, 'interact': True}, {'id': 2, 'interact': True}], ensure_ascii=False),
            json.dumps([{'id': 1, 'comment': '今天股市涨停了吧'},
                        {'id': 2, 'comment': '这张构图真好看'}], ensure_ascii=False),
        ])
        stats = InteractionPipeline(model).run_batch(self.inbox)
        self.assertEqual(stats['selected'], 2)
        self.assertEqual(stats['commented'], 1)
        comments = [r[3] for r in self.inbox.approved()]
        self.assertIn('这张构图真好看', comments)
        self.assertNotIn('股市', ' '.join(comments))
    def test_sensitive_source_not_selected(self):
        self.inbox.db.execute("UPDATE moment_inbox SET text='今天股市涨停了吧' WHERE id=1")
        self.inbox.db.commit()
        model = FakeModel([json.dumps([{'id': 1, 'interact': True}])])
        stats = InteractionPipeline(model).run_batch(self.inbox)
        self.assertEqual(stats['selected'], 0)
        self.assertEqual(model.calls, 1)

    def test_composer_cannot_promote_unselected_id(self):
        model = FakeModel([
            json.dumps([{'id': 1, 'interact': True}]),
            json.dumps([{'id': 2, 'comment': '好可爱！'}, {'id': 1, 'comment': '好软萌！'}])])
        stats = InteractionPipeline(model).run_batch(self.inbox)
        self.assertEqual([r[0] for r in self.inbox.approved()], [1])
        self.assertEqual(stats['commented'], 1)

    def test_bad_decision_format(self):
        model = FakeModel(['不是JSON'])
        with self.assertRaises(ValueError):
            InteractionPipeline(model).run_batch(self.inbox)
    def test_empty_inbox(self):
        model = FakeModel([])
        stats = InteractionPipeline(model).run_batch(MomentInbox(sqlite3.connect(':memory:')))
        self.assertEqual(stats, {'collected': 0})
        self.assertEqual(model.calls, 0)


class WhitelistTests(unittest.TestCase):
    """whitelist_only 真生效：没名单 fail-closed 不花额度；有名单只放行名单内作者。"""

    def setUp(self):
        self.inbox = MomentInbox(sqlite3.connect(':memory:'))
        for i, author in enumerate([' Alice', 'Bob', '很帅的年糕']):
            self.inbox.add(author, '动态内容%d' % i, False, 'fp%d' % i)

    def test_no_friends_list_blocks_without_model_call(self):
        """whitelist_only=true 但没配 friends：直接跳过，零模型调用。"""
        model = FakeModel([])
        pipe = InteractionPipeline(model, {'whitelist_only': True})
        stats = pipe.run_batch(self.inbox)
        self.assertEqual(stats.get('skipped'), 'whitelist_only_no_friends')
        self.assertEqual(stats['collected'], 3)
        self.assertEqual(model.calls, 0)          # 没花额度
        self.assertEqual(self.inbox.pending_count(), 3)   # 状态不变，下次可重试

    def test_whitelist_off_ignores_missing_list(self):
        """whitelist_only=false（或缺省）：没有 friends 也正常跑。"""
        model = FakeModel([
            json.dumps([{'id': 1, 'interact': True, 'reason': '有趣'},
                        {'id': 2, 'interact': False, 'reason': ''},
                        {'id': 3, 'interact': True, 'reason': '接梗'}], ensure_ascii=False),
            json.dumps([{'id': 1, 'comment': '哈哈哈'}], ensure_ascii=False),
        ])
        pipe = InteractionPipeline(model, {'whitelist_only': False})
        stats = pipe.run_batch(self.inbox)
        self.assertEqual(stats['selected'], 2)
        self.assertEqual(model.calls, 2)

    def test_items_carry_in_whitelist_flag(self):
        """决策官收到的条目带 in_whitelist 标记；系统提示词含白名单硬约束。"""
        captured = {}
        class SpyModel:
            def call(self, messages, max_tokens=1800):
                captured['system'] = messages[0]['content']
                captured['items'] = json.loads(messages[-1]['content'])
                return json.dumps([{'id': i, 'interact': False, 'reason': ''}
                                   for i in (1, 2, 3)], ensure_ascii=False)
        pipe = InteractionPipeline(SpyModel(), {'whitelist_only': True,
                                                'friends': ['Alice', '很帅的年糕']})
        pipe.run_batch(self.inbox)
        flags = {it['author'].strip(): it['in_whitelist'] for it in captured['items']}
        self.assertTrue(flags['Alice'])
        self.assertTrue(flags['很帅的年糕'])
        self.assertFalse(flags['Bob'])
        self.assertIn('白名单模式', captured['system'])

    def test_model_cannot_override_whitelist(self):
        model = FakeModel([
            json.dumps([{'id': 1, 'interact': True}, {'id': 2, 'interact': True}]),
            json.dumps([{'id': 1, 'comment': '好可爱！'}, {'id': 2, 'comment': '好软萌！'}])])
        stats = InteractionPipeline(model, {'whitelist_only': True,
                                           'friends': ['Alice']}).run_batch(self.inbox)
        self.assertEqual(stats['selected'], 1)
        self.assertEqual([r[0] for r in self.inbox.approved()], [1])

    def test_whitelist_off_has_no_constraint_in_prompt(self):
        captured = {}
        class SpyModel:
            def call(self, messages, max_tokens=1800):
                captured['system'] = messages[0]['content']
                return json.dumps([{'id': i, 'interact': False, 'reason': ''}
                                   for i in (1, 2, 3)], ensure_ascii=False)
        InteractionPipeline(SpyModel(), {}).run_batch(self.inbox)
        self.assertNotIn('白名单模式', captured['system'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
