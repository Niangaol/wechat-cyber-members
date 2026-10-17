"""窗口树解析测试：它是所有 UI 操作的地基，正则一坏全盘皆输。"""
import sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent / 'src'))
import screen

FIXTURE = '''
xwininfo: Window id: 0x21f (the root window) (has no name)

  Root window id: 0x21f (the root window) (has no name)
  Parent window id: 0x0 (none)
     3 children:
     0xe00010 "Weixin": ("wechat" "wechat")  1021x740+0+0  +0+0
     0xe00090 "wechat": ("wechat" "wechat")  130x125+573+337  +573+337
     0xa00004 (has no name): ()  1x1+-1+-1  +-1+-1
'''


class WindowParseTests(unittest.TestCase):
    def test_parses_title_size_and_absolute_position(self):
        with patch.object(screen, '_xwininfo_tree', return_value=FIXTURE):
            wins = screen.list_x_windows(':99')
        self.assertEqual(len(wins), 3, '三行窗口都要认出来')
        main = wins[0]
        self.assertEqual((main['id'], main['title']), ('0xe00010', 'Weixin'))
        self.assertEqual((main['w'], main['h']), (1021, 740))
        self.assertEqual((main['abs_x'], main['abs_y']), (0, 0))
        unnamed = wins[2]
        self.assertEqual(unnamed['title'], '', '没有名字的窗口也要解析出来')
        self.assertEqual((unnamed['x'], unnamed['y']), (-1, -1), '负坐标不能丢')

    def test_picks_the_biggest_wechat_window_as_client(self):
        with patch.object(screen, '_xwininfo_tree', return_value=FIXTURE):
            found = screen.find_wechat_windows(':99')
        self.assertIsNotNone(found.get('client'))
        self.assertEqual(found['client']['w'], 1021, '取面积最大的那个作为客户区')


if __name__ == '__main__':
    unittest.main()
