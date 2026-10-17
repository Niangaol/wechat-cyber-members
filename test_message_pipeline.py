import sqlite3, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
from test_integration import BASE_CFG, make_resident, stop_patches
from visual_parse import extract_messages, classify
from memory import ChatMemory
import multimedia

def frame(media=False, extra=False):
    im=Image.new('RGB',(1021,740),(237,237,237));d=ImageDraw.Draw(im)
    d.rectangle((305,150,337,182),fill=(70,100,220))
    d.text((355,150),'sender',fill=(150,150,150))
    d.rounded_rectangle((351,170,450,210),radius=5,fill='white')
    d.text((365,185),'hello',fill='black')
    d.text((640,240),'14:14',fill=(150,150,150))
    if media:
        d.rectangle((305,340,337,372),fill=(70,100,220))
        d.text((355,340),'sender',fill=(150,150,150))
        d.rounded_rectangle((356,365,614,557),radius=5,fill='white')
        d.rectangle((380,385,590,535),fill=(240,200,30))
    if extra:
        d.rectangle((961,260,993,292),fill=(70,100,220))
        d.rounded_rectangle((650,260,944,305),radius=5,fill=(149,235,105))
        d.text((665,270),'reply',fill='black')
    return im

class ParserTests(unittest.TestCase):
    def test_sender_time_avatar_excluded_and_bottom_image_preserved(self):
        messages=extract_messages(frame(media=True))
        self.assertEqual(len(messages),2)
        self.assertGreaterEqual(messages[0]['bbox'][1],170)
        self.assertLess(messages[0]['bbox'][3],240)
        self.assertGreater(messages[0]['bbox'][0],337)
        self.assertGreater(messages[1]['bbox'][3],548)
        self.assertFalse(any(m['at_me'] for m in messages))
    def test_outgoing_panel_has_correct_direction(self):
        messages=extract_messages(frame(extra=True))
        self.assertEqual([m['direction'] for m in messages],['in','out'])
    def test_colored_image_with_ocr_labels_stays_image(self):
        im=Image.new('RGB',(200,180),(240,200,30))
        self.assertEqual(classify(im,'FRONT VIEW'),'image')
    def test_green_text_is_not_an_image(self):
        self.assertEqual(classify(Image.new('RGB',(300,70),(149,235,105)),'hello'),'text')
    def test_caption_changes_do_not_change_bubble_signature(self):
        a=frame();b=a.copy();ImageDraw.Draw(b).text((640,240),'15:15',fill='black')
        self.assertEqual(extract_messages(a)[0]['signature'],extract_messages(b)[0]['signature'])

class TimelineTests(unittest.TestCase):
    def test_context_includes_only_own_timeline(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close);m=ChatMemory(db)
        m.add_timeline('group:A','in','image','image','a.png')
        m.add_timeline('direct:B','in','text','private')
        self.assertEqual(m.context_for('group:A')['timeline'][0]['image_path'],'a.png')
        self.assertEqual(m.context_for('direct:B')['timeline'][0]['text'],'private')
        self.assertEqual(len(m.context_for('group:A')['timeline']),1)
    def test_timeline_image_reaches_model_request_without_network(self):
        from multimodal import StepPlan
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'image.png';Image.new('RGB',(20,20),'yellow').save(p)
            ctx={'timeline':[{'direction':'in','kind':'image','text':'','image_path':str(p)}]}
            model=StepPlan(BASE_CFG)
            # 图片只在"本次新消息里带图"时才挂给模型（带图比纯文字慢 4 倍），
            # 所以这里的新消息必须是图片消息。
            fresh=[{'direction':'in','kind':'image','text':''}]
            with patch.object(model,'call',return_value='看到了') as call:
                self.assertEqual(model.reply(fresh,[],[],chat_context=ctx),'看到了')
            parts=call.call_args.args[0][-1]['content']
            self.assertEqual(parts[1]['type'],'image_url')
            self.assertTrue(parts[1]['image_url']['url'].startswith('data:image/png;base64,'))

    def test_text_only_message_skips_timeline_images(self):
        from multimodal import StepPlan
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'image.png';Image.new('RGB',(20,20),'yellow').save(p)
            ctx={'timeline':[{'direction':'in','kind':'image','text':'','image_path':str(p)}]}
            model=StepPlan(BASE_CFG)
            with patch.object(model,'call',return_value='在的') as call:
                self.assertEqual(model.reply([{'direction':'in','kind':'text','text':'在吗'}],
                                             [],[],chat_context=ctx),'在的')
            parts=call.call_args.args[0][-1]['content']
            # 纯文字消息的 user content 是 JSON 字符串（分段数组才会是 list）
            self.assertIsInstance(parts,str)
            self.assertNotIn('image_url',parts)
    def test_media_names_cannot_collide_or_escape(self):
        with tempfile.TemporaryDirectory() as td,patch.object(multimedia,'STATE',Path(td)):
            a=multimedia.inbox_media_dir('direct:A/B');b=multimedia.inbox_media_dir('direct:A?B')
            self.assertNotEqual(a,b)
            self.assertEqual(multimedia.inbox_media_dir('..').parent,Path(td)/'media'/'inbox')
    def test_observe_baseline_no_replay_then_new_media_enqueued(self):
        cfg=dict(BASE_CFG,group_whitelist=['G'])
        r=make_resident(cfg);self.addCleanup(stop_patches,r);self.addCleanup(r.db.close)
        class UI:
            image=frame()
            def capture(self):return self.image
            def chat_image(self,im):return im.crop((283,72,1021,584))
        ui=UI()
        # 批量 OCR 接口：按气泡数量返回等长文字列表（force 参数见 observe_one）
        def fake_ocr(u,img,bboxes,model=None,aliases=(),force=False):
            self.assertEqual(len(bboxes),len(extract_messages(img)))
            return ['hello']*len(bboxes)
        with patch('visual_parse.ocr_bubbles',side_effect=fake_ocr):
            self.assertFalse(r.observe_one(cfg,ui,None,'G',ui.image))
            self.assertEqual(r.quota.depth(),0)
            self.assertEqual(r.memory.get_timeline('group:G'),[])
            self.assertFalse((Path(r._tmp)/'media').exists())
            ui.image=frame(media=True)
            self.assertTrue(r.observe_one(cfg,ui,None,'G',ui.image))
            timeline=r.memory.context_for('group:G')['timeline']
            self.assertEqual(len(timeline),1)
            self.assertEqual(timeline[0]['kind'],'image')
            self.assertTrue(Path(timeline[0]['image_path']).exists())
            self.assertEqual(r.memory.context_for('direct:B')['timeline'],[])
            self.assertFalse(r.observe_one(cfg,ui,None,'G',ui.image))
            self.assertEqual(r.quota.depth(),1)

    def test_fresh_message_forces_model_ocr(self):
        """回归：本地 OCR 读出含 CJK 的乱码（如'让 6"'）时，needs_model_ocr 启发式
        会认为"读得可靠"而不调模型，错字就原样入队、回复跟着跑偏。
        有新消息必须强制走一次批量模型 OCR（模型调用次数=新消息批次数）。"""
        cfg = dict(BASE_CFG, group_whitelist=['G'])
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        class UI:
            def __init__(self):
                self.image = frame()
            def capture(self):
                return self.image
            def chat_image(self, im):
                return im.crop((283, 72, 1021, 584))
        ui = UI()
        seen = []
        def fake_ocr(u, img, bboxes, model=None, aliases=(), force=False):
            seen.append(force)
            # 含 CJK 的乱码：能骗过"零 CJK 才触发"的启发式
            return ['让 6"'] * len(bboxes)
        with patch('visual_parse.ocr_bubbles', side_effect=fake_ocr):
            self.assertFalse(r.observe_one(cfg, ui, None, 'G', ui.image))
            self.assertEqual(seen, [])          # 只建基线：零额度
            ui.image = frame(media=True)
            self.assertTrue(r.observe_one(cfg, ui, None, 'G', ui.image))
            self.assertEqual(seen, [True])      # 有新消息：强制一次批量模型 OCR

    def test_monitoring_without_fresh_message_costs_no_model(self):
        """轮询/指纹对比/建基线全程零模型调用（用户明确要求）。"""
        cfg = dict(BASE_CFG, group_whitelist=['G'])
        r = make_resident(cfg)
        self.addCleanup(stop_patches, r)
        self.addCleanup(r.db.close)
        class UI:
            def __init__(self):
                self.image = frame()
            def capture(self):
                return self.image
            def chat_image(self, im):
                return im.crop((283, 72, 1021, 584))
        ui = UI()
        seen = []
        def fake_ocr(u, img, bboxes, model=None, aliases=(), force=False):
            seen.append(force)
            return ['hello'] * len(bboxes)
        model = unittest.mock.Mock()
        model.key.return_value = 'k'
        with patch('visual_parse.ocr_bubbles', side_effect=fake_ocr):
            self.assertFalse(r.observe_one(cfg, ui, model, 'G', ui.image))
            self.assertFalse(r.observe_one(cfg, ui, model, 'G', ui.image))
            self.assertEqual(seen, [])
            self.assertEqual(r.quota.depth(), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
