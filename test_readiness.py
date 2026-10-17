"""运行快照必须不创建状态库、不迁移表、不更改授权。"""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location('readiness', Path(__file__).parent / 'wsl' / 'readiness.py')
readiness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(readiness)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'config').mkdir()
        (self.root / 'config' / 'resident.json').write_text(json.dumps({
            'interact': {'enabled': False, 'friends': []},
            'automation': {'enabled': True}, 'direct_policy': 'blacklist'}))
        self.state = self.root / 'state'

    def test_missing_state_not_created(self):
        result = readiness.snapshot(self.root, self.state)
        self.assertFalse(result['ledger_exists'])
        self.assertFalse(self.state.exists())

    def test_existing_database_not_migrated_or_written(self):
        self.state.mkdir()
        path = self.state / 'ledger.sqlite'
        db = sqlite3.connect(path)
        db.execute('CREATE TABLE moments(state TEXT, published REAL)')
        db.execute("INSERT INTO moments VALUES('DRAFT', NULL)")
        db.commit()
        db.close()
        original = path.read_bytes()
        result = readiness.snapshot(self.root, self.state)
        self.assertEqual(result['ledger_states'], {'moments': {'DRAFT': 1}})
        self.assertEqual(result['published_with_timestamp'], 0)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), ['ledger.sqlite'])

    def test_approval_contents_not_exposed_or_modified(self):
        self.state.mkdir()
        token = self.state / 'APPROVE_INTERACT'
        token.write_text('sensitive-token-contents')
        (self.state / 'STOP').touch()
        result = readiness.snapshot(self.root, self.state)
        self.assertTrue(result['approval_present']['APPROVE_INTERACT'])
        self.assertTrue(result['stop_present'])
        self.assertNotIn('sensitive-token-contents', json.dumps(result))
        self.assertEqual(token.read_text(), 'sensitive-token-contents')


if __name__ == '__main__':
    unittest.main()
