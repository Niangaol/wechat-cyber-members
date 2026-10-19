"""未读角标触发线：角标亮着就去看，头像里的红色不算。

2026-10-19 的坑：观察只靠"行像素签名变没变"决定要不要切进群。签名连续 6 分钟
不变，新消息就只能等 10 分钟一次的兜底全扫。角标直接回答"有没有没读的消息"，
比"和上一轮比变没变"更硬，所以补成第二条触发线。

同一天还实测到一个误报源：群头像是 9 张成员照拼的，整列红像素 179 个全落在
x 80–120 的头像里。所以检测只在列表列右端（x>=180）数红，头像的红色照片
天然被排除——这两个测试就是钉死这件事。
"""
import unittest
from PIL import Image, ImageDraw

from test_integration import BASE_CFG, make_resident, stop_patches
from chat_navigator import avatar_key, avatar_rows, row_unread, row_unread_px

NAMES = ['甲群', '乙群']
AVATARS = {100: (200, 60, 60), 180: (60, 140, 200)}   # 行中心 y -> 头像颜色


def frame(badge_row=None, red_avatar=False):
    """画一帧假的会话列表。badge_row=行中心 y 时在该行右端画一个红色未读角标。"""
    im = Image.new('RGB', (1021, 740), (237, 237, 237))
    d = ImageDraw.Draw(im)
    for cy, color in AVATARS.items():
        if red_avatar and cy == 100:
            color = (235, 40, 40)          # 纯红头像：误报源，必须不能触发
        d.rectangle((78, cy - 18, 110, cy + 18), fill=color)
        d.rectangle((121, cy - 16, 300, cy + 34), fill=(250, 250, 250))
        d.text((124, cy - 10), 'name', fill=(30, 30, 30))
    if badge_row is not None:
        # 微信未读角标：列表列右端的实心红圆，直径约 20px
        d.ellipse((262, badge_row - 11, 286, badge_row + 11), fill=(250, 81, 81))
    return im


class FakeUI:
    def __init__(self, image):
        self.image = image
    def capture(self):
        return self.image.copy()


class RowUnreadDetectorTests(unittest.TestCase):
    """检测器本身：只认列表列右端的实心红块。"""

    def test_plain_row_has_no_unread(self):
        img = frame()
        for (top, bot) in avatar_rows(img):
            self.assertEqual(row_unread_px(img, top, bot), 0)

    def test_badge_is_counted(self):
        img = frame(badge_row=180)
        rows = avatar_rows(img)
        top, bot = rows[1]
        self.assertGreaterEqual(row_unread_px(img, top, bot), 40)
        self.assertTrue(row_unread(img, top, bot)[0])

    def test_red_avatar_alone_does_not_count(self):
        """误报回归：头像里全是红色也不能当成未读。"""
        img = frame(red_avatar=True)
        for (top, bot) in avatar_rows(img):
            self.assertEqual(row_unread_px(img, top, bot), 0,
                             '头像照片的红色不该被当成未读角标')

    def test_disabled_by_config(self):
        img = frame(badge_row=180)
        top, bot = avatar_rows(img)[1]
        ok, px = row_unread(img, top, bot, {'observe_unread_badge': {'enabled': False}})
        self.assertFalse(ok)
        self.assertEqual(px, 0)

    def test_threshold_is_configurable(self):
        img = frame(badge_row=180)
        top, bot = avatar_rows(img)[1]
        ok, _ = row_unread(img, top, bot, {'observe_unread_badge': {'min_px': 99999}})
        self.assertFalse(ok, '阈值调大到像素数以上就不该触发')


class UnreadTriggerTests(unittest.TestCase):
    """接进 plan_visits 之后的行为。"""

    def setUp(self):
        self.cfg = dict(BASE_CFG)
        self.r = make_resident(self.cfg)
        self.addCleanup(stop_patches, self.r)
        self.addCleanup(self.r.db.close)
        self.r._avatar_of = {}
        self.r._row_sigs = {}
        self.r._row_y = {}
        self.r._unread_since = {}
        self.r._unread_px = {}
        self.r._last_sweep = 0

    def learn(self, img):
        for i, (top, bot) in enumerate(avatar_rows(img)):
            self.r._avatar_of[NAMES[i]] = avatar_key(img, (top + bot) // 2)

    def test_badge_alone_triggers_a_visit(self):
        """签名没变、只有角标亮：也要去看。这就是补这条触发线的原因。"""
        img = frame()
        self.learn(img)
        self.r.plan_visits(self.cfg, FakeUI(img), NAMES)      # 建基线
        self.assertEqual(self.r.plan_visits(self.cfg, FakeUI(img), NAMES), [])
        lit = frame(badge_row=180)
        self.assertEqual(self.r.plan_visits(self.cfg, FakeUI(lit), NAMES), [NAMES[1]])

    def test_badge_does_not_retrigger_every_cycle(self):
        """角标一直亮着不能每轮都切进去：账单会爆。"""
        img = frame(badge_row=180)
        self.learn(img)
        first = self.r.plan_visits(self.cfg, FakeUI(img), NAMES)
        self.assertIn(NAMES[1], first)
        # 同一帧再来一次：签名没变、角标还亮，但节流期内不该再选
        self.assertEqual(self.r.plan_visits(self.cfg, FakeUI(img), NAMES), [])

    def test_badge_rechecks_after_recheck_seconds(self):
        img = frame(badge_row=180)
        self.learn(img)
        self.r.plan_visits(self.cfg, FakeUI(img), NAMES)
        cfg = dict(self.cfg, observe_unread_badge={'recheck_s': 0})
        self.assertIn(NAMES[1], self.r.plan_visits(cfg, FakeUI(img), NAMES),
                      '超过 recheck 秒角标还在，就该复查')

    def test_badge_clearing_resets_the_throttle(self):
        lit = frame(badge_row=180)
        dark = frame()
        self.learn(dark)
        # 角标亮：第一次一定看
        self.assertIn(NAMES[1], self.r.plan_visits(self.cfg, FakeUI(lit), NAMES))
        # 同一帧再来：节流期内不该再看
        self.assertEqual(self.r.plan_visits(self.cfg, FakeUI(lit), NAMES), [])
        # 角标灭掉 = 行像素也变了，签名线照旧该看一次（这不是角标的功劳）
        self.assertIn(NAMES[1], self.r.plan_visits(self.cfg, FakeUI(dark), NAMES))
        self.assertEqual(self.r.plan_visits(self.cfg, FakeUI(dark), NAMES), [])
        # 灭了之后再次亮起：是新的 transitioning，应当立刻再看一次
        self.assertIn(NAMES[1], self.r.plan_visits(self.cfg, FakeUI(lit), NAMES))

    def test_disabled_badge_never_triggers_on_its_own(self):
        """关掉角标线后，只剩签名线；用 recheck_s=0 把两者区分开。"""
        cfg = dict(self.cfg, observe_unread_badge={'enabled': False, 'recheck_s': 0})
        img = frame(badge_row=180)
        self.learn(img)
        self.r.plan_visits(cfg, FakeUI(img), NAMES)          # 建基线
        self.assertEqual(self.r.plan_visits(cfg, FakeUI(img), NAMES), [],
                         '角标线关掉后，签名不变就不该再访问')

    def test_unread_due_respects_enabled_flag(self):
        cfg = dict(self.cfg, observe_unread_badge={'enabled': False})
        self.assertFalse(self.r._unread_due('甲群', True, 1000.0, cfg))
        self.assertEqual(self.r._unread_since, {}, '关掉时不该留下节流状态')

    def test_unread_due_throttles_while_lit(self):
        cfg = dict(self.cfg, observe_unread_badge={'recheck_s': 60})
        self.assertTrue(self.r._unread_due('甲群', True, 1000.0, cfg), '刚亮起该看')
        self.assertFalse(self.r._unread_due('甲群', True, 1001.0, cfg), '节流期内不该看')
        self.assertTrue(self.r._unread_due('甲群', True, 1061.0, cfg), '超过 recheck 该复查')
        self.assertFalse(self.r._unread_due('甲群', False, 1062.0, cfg), '灭了就不看')
        self.assertEqual(self.r._unread_since, {}, '灭了要清掉节流状态')

    def test_red_avatar_row_is_not_visited_for_unread(self):
        """误报回归：纯红头像的行不该被角标线选中。"""
        img = frame(red_avatar=True)
        self.learn(img)
        self.r.plan_visits(self.cfg, FakeUI(img), NAMES)
        self.assertEqual(self.r.plan_visits(self.cfg, FakeUI(img), NAMES), [])


if __name__ == '__main__':
    unittest.main()
