"""上线窗口测试：用户 2026-10-18 要求只在早上 8 点到晚上 10 点上线。

窗口判定是纯本地规则（不调模型、不花额度），但一旦写错就是"整天哑掉"或
"半夜乱说话"——所以逐条锁死，包括配置写错时的兜底方向。
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent/'src'))
from resident import Resident                                    # noqa: E402


def resident():
    return Resident.__new__(Resident)          # 只要判定函数，不需要完整初始化


class OnlineWindowTests(unittest.TestCase):
    def setUp(self):
        self.r = resident()

    def test_default_window_is_8_to_22(self):
        """配置整段缺失也按 8–22：这是用户明确要的作息，不是可选装饰。"""
        for hour, want in [(0, False), (7, False), (8, True), (12, True),
                           (21, True), (22, False), (23, False)]:
            with self.subTest(hour=hour):
                self.assertEqual(self.r.online_now({}, hour=hour)[0], want)

    def test_stop_hour_is_exclusive(self):
        """22 点整下班、8 点整上班：边界不含结束点。"""
        self.assertEqual(self.r.online_now({}, hour=22),
                         (False, 'outside_window'))
        self.assertEqual(self.r.online_now({}, hour=8), (True, 'in_window'))

    def test_reason_names_the_state(self):
        self.assertEqual(self.r.online_now({}, hour=3)[1], 'outside_window')
        self.assertEqual(self.r.online_now({}, hour=15)[1], 'in_window')

    def test_custom_window_is_honoured(self):
        cfg = {'online_window': {'start_hour': 9, 'stop_hour': 21}}
        self.assertFalse(self.r.online_now(cfg, hour=8)[0])
        self.assertTrue(self.r.online_now(cfg, hour=9)[0])
        self.assertTrue(self.r.online_now(cfg, hour=20)[0])
        self.assertFalse(self.r.online_now(cfg, hour=21)[0])

    def test_disabled_means_always_online(self):
        cfg = {'online_window': {'enabled': False}}
        for hour in (0, 3, 8, 23):
            with self.subTest(hour=hour):
                self.assertEqual(self.r.online_now(cfg, hour=hour),
                                 (True, 'window_disabled'))

    def test_broken_config_fails_open_not_silent(self):
        """配置写错时按始终在线处理，并且原因能说清楚——不能悄悄哑掉。"""
        for cfg in ({'online_window': {'start_hour': 'abc', 'stop_hour': 22}},
                    {'online_window': {'start_hour': 22, 'stop_hour': 8}},
                    {'online_window': {'start_hour': -1, 'stop_hour': 22}},
                    {'online_window': {'start_hour': 8, 'stop_hour': 99}}):
            with self.subTest(cfg=cfg):
                inside, why = self.r.online_now(cfg, hour=3)
                self.assertTrue(inside)
                self.assertIn(why, ('bad_config', 'bad_window'))

    def test_string_hours_are_accepted(self):
        """JSON 里手写成字符串也别炸：转得动就用，转不动按坏配置兜底。"""
        cfg = {'online_window': {'start_hour': '8', 'stop_hour': '22'}}
        self.assertEqual(self.r.online_now(cfg, hour=9)[0], True)
        self.assertEqual(self.r.online_now(cfg, hour=23)[0], False)

    def test_real_config_file_matches_defaults(self):
        """线上配置和代码默认值必须一致：改了一个忘了另一个会很难查。"""
        import json
        cfg = json.loads((Path(__file__).parent/'config'/'resident.json')
                         .read_text(encoding='utf-8'))
        win = cfg.get('online_window') or {}
        self.assertEqual(int(win.get('start_hour', 8)), 8)
        self.assertEqual(int(win.get('stop_hour', 22)), 22)
        self.assertNotEqual(win.get('enabled'), False)



def test_test_harness_disables_the_window(self):
    '''回归：测试夹具必须关掉窗口，否则整套测试依赖墙上时钟。

    2026-10-18 22:10 实测：窗口一上线，12 个集成测试在半夜同时红、
    早上全过——这种看时辰的测试比没有测试更糟，所以钉死在这里。
    '''
    sys.path.insert(0, str(Path(__file__).parent))
    from test_integration import BASE_CFG
    self.assertEqual((BASE_CFG.get('online_window') or {}).get('enabled'), False)
if __name__ == '__main__':
    unittest.main()
