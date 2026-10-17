import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
import test_multi_chat
from test_multi_chat import FakeUI, tsv_row
import chat_anchors as anchors
from chat_navigator import ChatNavigator, find_chat_in_list, _line_matches
from wechat_ui import SafetyError, title_matches

class TitleOcrFoldTests(unittest.TestCase):
    """标题核验的 OCR 折叠：I/l/1/| 分不出来时也要能认对目标。

    实测：群名「Vibe AI Lab 招新交流群」在标题栏被读成「Vibe Al Lab 招新交流群」，
    严格比较导致这个群一直切换失败（列表锚点找到了、也点开了，却判为"标题不符"）。
    折叠只覆盖这一族字符，且要求整个标题一致——不是放宽成"像就行"。
    """

    def test_ai_read_as_al_is_accepted(self):
        self.assertTrue(title_matches("Vibe AI Lab 招新交流群",
                                      "Vibe Al Lab 招新交流群(214)", True))

    def test_group_member_suffix_still_accepted(self):
        self.assertTrue(title_matches("人机", "人机(11)", True))

    def test_direct_chat_does_not_accept_suffix(self):
        self.assertFalse(title_matches("很帅的年糕", "很帅的年糕(3)", False))

    def test_chinese_ocr_errors_stay_rejected(self):
        """CJK 错字不折叠：读错字就必须拒绝（"很诈的年粒"不是"很帅的年糕"）。"""
        self.assertFalse(title_matches("很帅的年糕", "很诈的年粒", False))

    def test_no_substring_matching(self):
        self.assertFalse(title_matches("人机", "人机交流群", True))
        self.assertFalse(title_matches("Vibe AI Lab 招新交流群",
                                       "Vibe AI Lab 招新交流群备用(5)", True))


class LineMatchTests(unittest.TestCase):
    def test_name_glued_with_timestamp_still_matches(self):
        """微信列表把「名字+时间+预览」粘成一行：Deep...Yesterday 必须能匹配 Deepseek。

        2026-10-17 实测事故：新好友 Deepseek 因为这一行匹配不上，机器人一直看不见他的会话
        （chats_observed 2/3，日志里连观察记录都没有）。
        """
        self.assertTrue(_line_matches('deepseek', 'Deep...Yesterday'))
        self.assertTrue(_line_matches('deepseek', 'Deep...'))
        self.assertTrue(_line_matches('豆包', '豆包昨天'))
        self.assertTrue(_line_matches('Deepseek', 'Deep...Yesterday'))  # 大小写也不敏感

    def test_short_group_name_matches_inside_noisy_line(self):
        """两字群名（人机）要能在带头像噪声的列表行里被找到。

        2026-10-17 实测：列表 OCR 出来是"oae人机"，旧逻辑在 2 字名字上直接 return False，
        机器人一直看不见这个群（chats_observed 3/4，日志里连观察记录都没有）。
        """
        self.assertTrue(_line_matches('人机', 'oae人机'))
        self.assertTrue(_line_matches('人机', '人机'))
        self.assertFalse(_line_matches('人机', 'oae机器'))
        self.assertFalse(_line_matches('人机', 'oae'))

    def test_other_names_still_rejected(self):
        """放宽的只是"行首前缀"，别人的名字不能被误配。"""
        self.assertFalse(_line_matches('deepseek', 'Weixi...Yesterday'))
        self.assertFalse(_line_matches('deepseek', 'FileTransfer'))
        self.assertFalse(_line_matches('deepseek', ''))


class AnchorTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p=patch.object(anchors,'ROOT',Path(tmp.name));p.start();self.addCleanup(p.stop)
        self.image=Image.new('RGB',(1021,740),(237,237,237))
        ImageDraw.Draw(self.image).rectangle((310,30,340,45),fill='black')
    def test_title_anchor_cannot_be_borrowed_by_another_name(self):
        self.image.crop(anchors.TITLE_BOX).save(anchors.anchor_path('A','title'))
        self.assertTrue(anchors.title_anchor_matches('A',self.image))
        self.assertFalse(anchors.title_anchor_matches('B',self.image))
    def test_changed_title_refused(self):
        self.image.crop(anchors.TITLE_BOX).save(anchors.anchor_path('A','title'))
        other=self.image.copy();ImageDraw.Draw(other).rectangle((350,30,370,45),fill='black')
        self.assertFalse(anchors.title_anchor_matches('A',other))
    def test_list_anchor_tracks_row_and_selection_background(self):
        d=ImageDraw.Draw(self.image);d.rectangle((125,130,145,145),fill='black')
        anchors.text_mask(self.image.crop((120,125,185,147))).save(anchors.anchor_path('A','list'))
        pos=anchors.find_list_anchor('A',self.image)
        self.assertIsNotNone(pos)
        shifted=Image.new('RGB',self.image.size,(210,210,210))
        ImageDraw.Draw(shifted).rectangle((125,230,145,245),fill='black')
        self.assertEqual(anchors.find_list_anchor('A',shifted),(pos[0],pos[1]+100))
    def test_duplicate_list_anchor_refused(self):
        d=ImageDraw.Draw(self.image)
        for y in [130,230]:d.rectangle((125,y,145,y+15),fill='black')
        anchors.text_mask(self.image.crop((120,125,185,147))).save(anchors.anchor_path('A','list'))
        self.assertIsNone(anchors.find_list_anchor('A',self.image))
    def test_duplicate_ocr_candidates_refused(self):
        ui=FakeUI(tsv_row('很帅...',100,120)+tsv_row('很帅...',100,240))
        self.assertIsNone(find_chat_in_list(ui,ui.capture(),'很帅的年糕'))
    def test_navigation_uses_only_mouse_and_rechecks_title(self):
        ui=FakeUI();ui.last_abs=(129,30)
        with patch('chat_navigator.find_chat_in_list',return_value=(160,100)), \
             patch('chat_navigator.time.sleep'), \
             patch.object(ui,'ocr',side_effect=['其他人','很帅的年糕']):
            ChatNavigator(ui).switch_to('很帅的年糕')
        self.assertIn(['xdotool','mousemove','289','130'],ui.clicks)
        self.assertFalse(hasattr(ui,'clipboard'))
    def test_missing_list_target_has_no_input(self):
        ui=FakeUI();ui.ocr=lambda *args:'其他人'
        with self.assertRaises(SafetyError):ChatNavigator(ui).switch_to('很帅的年糕')
        # 找不到目标时允许在列表里滚轮（久没消息的会话会沉下去），
        # 但绝不左键点任何东西、不碰剪贴板、不进搜索框
        left=[c for c in ui.clicks if c[-1]=='1']
        self.assertEqual(left,[],'不能左键点击')
        self.assertFalse(hasattr(ui,'clipboard'))

if __name__=='__main__':unittest.main()
