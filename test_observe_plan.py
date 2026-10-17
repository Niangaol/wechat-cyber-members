"""观察计划：头像指纹认行、行没变就跳过、变了才访问。"""
import unittest
from PIL import Image, ImageDraw

from test_integration import BASE_CFG, make_resident, stop_patches
from chat_navigator import avatar_key, avatar_rows

NAMES = ['甲群', '乙群']
AVATARS = {100: (200, 60, 60), 180: (60, 140, 200)}   # 行中心 y -> 头像颜色


def frame(changed_row=None):
    """画一帧假的会话列表：头像色块 + 名字行/预览行。"""
    im = Image.new('RGB', (1021, 740), (237, 237, 237))
    d = ImageDraw.Draw(im)
    for cy, color in AVATARS.items():
        d.rectangle((78, cy - 18, 110, cy + 18), fill=color)      # 头像
        d.rectangle((121, cy - 16, 300, cy + 34), fill=(250, 250, 250))  # 行底
        d.text((124, cy - 10), 'name', fill=(30, 30, 30))
    if changed_row:
        d.rectangle((121, changed_row + 2, 290, changed_row + 30),
                    fill=(120, 120, 120))                     # 预览变化
    return im


class FakeUI:
    def __init__(self, image):
        self.image = image
    def capture(self):
        return self.image.copy()


class ObservePlanTests(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(BASE_CFG)
        self.r = make_resident(self.cfg)
        self.addCleanup(stop_patches, self.r)
        self.addCleanup(self.r.db.close)
        self.r._avatar_of = {}
        self.r._row_sigs = {}
        self.r._row_y = {}
        self.r._last_sweep = 0

    def learn(self, img):
        # 用真实行检测得到的中心，和 plan_visits 的算法保持一致
        for i, (top, bot) in enumerate(avatar_rows(img)):
            self.r._avatar_of[NAMES[i]] = avatar_key(img, (top + bot) // 2)

    def test_unknown_chats_are_visited_in_small_batches(self):
        ui = FakeUI(frame())
        chosen = self.r.plan_visits(dict(self.cfg, observe_sweep_batch=2), ui, NAMES)
        self.assertEqual(chosen, NAMES[:2])       # 每次最多学 2 个

    def test_unchanged_rows_are_skipped(self):
        img = frame()
        self.learn(img)
        # 第一次见到已知头像：先建基线（会访问一次），之后行不变就不再来
        self.r.plan_visits(self.cfg, FakeUI(img), NAMES)
        self.assertEqual(self.r.plan_visits(self.cfg, FakeUI(img), NAMES), [])

    def test_changed_row_is_the_only_visit(self):
        img = frame()
        self.learn(img)
        self.r.plan_visits(self.cfg, FakeUI(img), NAMES)   # 建立基线
        self.assertEqual(
            self.r.plan_visits(self.cfg, FakeUI(frame(changed_row=180)), NAMES),
            [NAMES[1]])

    def test_avatar_rows_never_sees_fewer_than_drawn(self):
        rows = avatar_rows(frame())
        self.assertGreaterEqual(len(rows), 2)


if __name__ == '__main__':
    unittest.main()
