"""协作式 UI 锁：不同线程竞争、嵌套重入、异常释放及各入口拒绝忙碌。"""
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from ui_lease import ui_lease, UILeaseBusy
from test_integration import BASE_CFG, make_resident, stop_patches
from test_moment_release import Base
from moment_release import ReleaseError


class LeaseTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)

    def test_same_thread_nested_lease_is_reentrant(self):
        with ui_lease(self.state):
            with ui_lease(self.state):
                self.assertTrue((self.state / 'wechat-ui.lock').exists())
        self.assertEqual((self.state / 'wechat-ui.lock').stat().st_mode & 0o777, 0o600)

    def test_other_thread_cannot_enter(self):
        def contender():
            with self.assertRaises(UILeaseBusy):
                with ui_lease(self.state):
                    self.fail('不能进入另一个执行者持有的UI')
        with ui_lease(self.state), ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(contender).result(timeout=5)

    def test_inner_release_does_not_unlock_outer(self):
        with ui_lease(self.state):
            with ui_lease(self.state):
                pass
            def contender():
                try:
                    with ui_lease(self.state):
                        return False
                except UILeaseBusy:
                    return True
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertTrue(pool.submit(contender).result(timeout=5))

    def test_exception_releases_kernel_lock(self):
        with self.assertRaises(ValueError):
            with ui_lease(self.state):
                raise ValueError('abort')
        with ui_lease(self.state):
            pass

    def test_resident_busy_skips_before_navigation_or_models(self):
        r = make_resident(BASE_CFG)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        with patch('resident.ui_lease', side_effect=UILeaseBusy('busy')), patch.object(r, '_cycle') as body:
            r.cycle(BASE_CFG)
        body.assert_not_called()
        import json
        result = json.loads((Path(r._tmp) / 'status.json').read_text())
        self.assertEqual(result['state'], 'ui_busy')
        self.assertTrue(result['skipped'])


class PublicationLeaseTests(Base):
    def test_busy_release_does_not_touch_ui_or_claim_post(self):
        rel = self._rel()
        rel.approve(1)
        with patch('moment_release.ui_lease', side_effect=UILeaseBusy('busy')):
            with self.assertRaises(ReleaseError):
                rel.publish()
        self.assertEqual(rel.ui.commands, [])
        self.assertFalse(rel.attempt_path.exists())


if __name__ == '__main__':
    unittest.main()
