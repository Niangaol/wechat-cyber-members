"""独立发图工具；全部UI和子进程mock，仅临时目录写入。"""
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent / 'src'))
import image_send_tool as tool
from ui_lease import UILeaseBusy
from wechat_ui import SafetyError


class ToolTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state = self.root / 'state'
        self.config = self.root / 'cfg.json'
        self.cfg = {'display': ':99', 'target_chat': '本人', 'direct_enabled': True,
                    'direct_whitelist': ['本人'], 'group_whitelist': ['测试群'],
                    'direct_blacklist': [], 'chat_types': {'测试群':'group'}}
        self.save()
        self.image = self.root / 'test.png'
        Image.new('RGB',(64,48),'red').save(self.image)
        self.digest = tool.prepare_image(self.image)[1]['sha256']
        self.ui = Mock()
        self.ui.send_png.return_value = {'status':'SUBMITTED', 'delivery_confirmed':False}
        self.factory = Mock(return_value=self.ui)
        self.nav = Mock()
        self.nav_factory = Mock(return_value=self.nav)

    def save(self):
        self.config.write_text(json.dumps(self.cfg),encoding='utf-8')

    def run_tool(self, **kwargs):
        args = dict(config_path=self.config,state_dir=self.state,
                    ui_factory=self.factory,navigator_factory=self.nav_factory)
        args.update(kwargs)
        return tool.run_tool('测试群',self.image,**args)

    def execute(self, **kwargs):
        args=dict(execute=True,confirm_chat='测试群',expected_sha256=self.digest,request_id='test-1')
        args.update(kwargs)
        return self.run_tool(**args)

    def test_preflight_has_no_ui_no_state_no_config_change(self):
        original = self.config.read_bytes()
        self.assertEqual(self.run_tool()['status'],'PREFLIGHT')
        self.factory.assert_not_called()
        self.assertFalse(self.state.exists())
        self.assertEqual(self.config.read_bytes(),original)

    def test_authorization_is_explicit(self):
        for name in ['陌生群','测试群备用',' 测试群','测试群(2)']:
            with self.subTest(name=name), self.assertRaises(tool.ImageToolError):
                tool.authorize(self.cfg,name)
        self.assertEqual(tool.authorize(self.cfg,'本人'),'direct:本人')
        self.cfg['direct_enabled']=False
        with self.assertRaises(tool.ImageToolError): tool.authorize(self.cfg,'本人')
        self.cfg['direct_enabled']=True
        self.cfg['direct_blacklist']=['本人']
        with self.assertRaises(tool.ImageToolError): tool.authorize(self.cfg,'本人')

    def test_execute_requires_chat_hash_and_id_confirmation(self):
        for kw in [dict(confirm_chat=None),dict(expected_sha256='bad'),dict(request_id=None),dict(request_id='../x')]:
            with self.subTest(kw=kw), self.assertRaises(tool.ImageToolError): self.execute(**kw)
        self.factory.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_file_changed_after_preflight_is_blocked(self):
        Image.new('RGB',(64,48),'blue').save(self.image)
        with self.assertRaises(tool.ImageToolError): self.execute()
        self.factory.assert_not_called()

    def test_busy_yields_without_ui_or_attempt_record(self):
        @contextmanager
        def busy(state):
            raise UILeaseBusy('busy')
            yield
        with self.assertRaises(UILeaseBusy): self.execute(lease_factory=busy)
        self.factory.assert_not_called()
        self.assertFalse((self.state/'image-tool').exists())

    def test_stop_blocks_without_ui(self):
        self.state.mkdir()
        (self.state/'STOP').touch()
        with self.assertRaises(tool.ImageToolError): self.execute()
        self.factory.assert_not_called()

    def test_success_binds_explicit_target_and_deduplicates(self):
        result=self.execute()
        self.assertEqual(result['status'],'SUBMITTED')
        self.assertFalse(result['delivery_confirmed'])
        self.nav.switch_to.assert_called_once_with('测试群')
        self.assertEqual(self.ui.send_png.call_args.args[1],'测试群')
        self.assertEqual(self.execute()['status'],'DUPLICATE_BLOCKED')
        self.assertEqual(self.execute(request_id='new-id')['status'],'DUPLICATE_BLOCKED')
        self.ui.send_png.assert_called_once()

    def test_uncertain_failure_persists_and_cannot_retry(self):
        self.ui.send_png.side_effect=SafetyError('uncertain')
        with self.assertRaises(SafetyError): self.execute()
        result=self.execute()
        self.assertEqual(result['prior_state'],'UNCERTAIN')
        self.ui.send_png.assert_called_once()

    def test_submitting_is_durable_before_return_and_crash(self):
        def fail(data, chat, guard, mark):
            mark()
            with sqlite3.connect(self.state/'image-tool/attempts.sqlite') as db:
                self.assertEqual(db.execute('SELECT state FROM attempts').fetchone()[0],'SUBMITTING')
            raise KeyboardInterrupt()
        self.ui.send_png.side_effect=fail
        with self.assertRaises(KeyboardInterrupt): self.execute()
        self.assertEqual(self.execute()['prior_state'],'UNCERTAIN')

    def test_revocation_during_navigation_blocks_sender(self):
        def navigate(chat):
            self.cfg['group_whitelist']=[]
            self.save()
        self.nav.switch_to.side_effect=navigate
        def send(data, chat, guard, mark): guard()
        self.ui.send_png.side_effect=send
        with self.assertRaises(tool.ImageToolError): self.execute()

    def test_png_encoding_and_metadata_removed(self):
        raw,info=tool.prepare_image(self.image)
        with Image.open(io.BytesIO(raw)) as im:
            self.assertEqual(im.format,'PNG')
            self.assertFalse(im.info)
        self.assertEqual(info['sha256'],self.digest)

    def test_jpeg_is_converted_resized_original_unchanged(self):
        p=self.root/'photo.jpg'
        Image.new('RGB',(2500,1600),'green').save(p)
        old=p.read_bytes()
        data,info=tool.prepare_image(p)
        self.assertLessEqual(info['width'],2048)
        self.assertTrue(data.startswith(b'\x89PNG'))
        self.assertEqual(p.read_bytes(),old)

    def test_animated_and_non_images_rejected(self):
        p=self.root/'anim.webp'
        frames=[Image.new('RGB',(8,8),color) for color in ('red','blue')]
        frames[0].save(p,save_all=True,append_images=frames[1:],duration=100)
        with self.assertRaises(tool.ImageToolError): tool.prepare_image(p)
        p=self.root/'not-image.png'
        p.write_text('no image')
        with self.assertRaises(Exception): tool.prepare_image(p)


class PixelTests(unittest.TestCase):
    def shot(self, preview=False):
        im=Image.new('RGB',(1021,740),(237,237,237))
        if preview: ImageDraw.Draw(im).rectangle((355,635,510,672),fill='red')
        return im

    def test_chat_area_cannot_fake_composer_preview(self):
        before=self.shot()
        after=before.copy()
        ImageDraw.Draw(after).rectangle((400,500,700,580),fill='black')
        self.assertFalse(tool.preview_changed(before,after))

    def test_real_composer_change_is_required(self):
        self.assertTrue(tool.preview_changed(self.shot(),self.shot(True)))
        self.assertTrue(tool.composer_empty(self.shot()))
        self.assertFalse(tool.composer_empty(self.shot(True)))

    def test_uniform_black_draft_is_not_empty(self):
        im=self.shot()
        ImageDraw.Draw(im).rectangle(tool.COMPOSER,fill='black')
        self.assertFalse(tool.composer_empty(im))


class SenderTests(PixelTests):
    def setUp(self):
        self.ui=tool.ImageUI({'display':':99'})
        self.ui.wid='0x1'
        self.ui.last_abs=(0,0)
        self.ui.key=Mock()
        self.ui.run=Mock(return_value=b'png-data')
        self.ui.clip_read=Mock(return_value=('UTF8_STRING',b'original'))
        self.ui.clip_write=Mock()
        self.ui._draft_text=Mock(return_value='')
        self.guard=Mock()
        self.mark=Mock()
        self.ui.verify_target=Mock(side_effect=[self.shot()]*4+[self.shot(True)]*3+[self.shot()])
        sleep=patch('image_send_tool.time.sleep')
        sleep.start()
        self.addCleanup(sleep.stop)

    def send(self): return self.ui.send_png(b'png-data','测试群',self.guard,self.mark)

    def test_success_rechecks_target_and_restores_clipboard(self):
        self.assertEqual(self.send()['status'],'SUBMITTED')
        self.ui.key.assert_any_call('Return')
        self.mark.assert_called_once()
        for call in self.ui.verify_target.call_args_list:
            self.assertEqual(call.kwargs,{'expected_chat':'测试群'})
        self.assertEqual(self.ui.clip_write.call_args.args,('UTF8_STRING',b'original'))

    def test_existing_draft_never_pastes(self):
        self.ui._draft_text.return_value='draft'
        with self.assertRaises(SafetyError): self.send()
        self.ui.key.assert_not_called()
        self.ui.clip_write.assert_not_called()

    def test_clipboard_mismatch_never_pastes(self):
        self.ui.run.return_value=b'wrong'
        with self.assertRaises(SafetyError): self.send()
        self.ui.key.assert_not_called()
        self.ui.clip_write.assert_called_with('UTF8_STRING',b'original')

    def test_no_preview_never_submits(self):
        self.ui.verify_target.side_effect=None
        self.ui.verify_target.return_value=self.shot()
        with self.assertRaises(SafetyError): self.send()
        self.assertNotIn(('Return',),[c.args for c in self.ui.key.call_args_list])
        self.mark.assert_not_called()

    def test_wrong_title_at_final_gate_never_submits(self):
        self.ui.verify_target.side_effect=[self.shot()]*4+[self.shot(True)]*2+[SafetyError('wrong target')]
        with self.assertRaises(SafetyError): self.send()
        self.assertNotIn(('Return',),[c.args for c in self.ui.key.call_args_list])

    def test_stop_after_mark_never_submits(self):
        self.mark.side_effect=lambda: setattr(self.guard,'side_effect',tool.ImageToolError('STOP'))
        with self.assertRaises(tool.ImageToolError): self.send()
        self.assertNotIn(('Return',),[c.args for c in self.ui.key.call_args_list])

    def test_uncleared_input_is_uncertain_not_success(self):
        self.ui.verify_target.side_effect=[self.shot()]*4+[self.shot(True)]*4
        with self.assertRaises(SafetyError): self.send()
        self.assertEqual([c.args for c in self.ui.key.call_args_list].count(('Return',)),1)


if __name__=='__main__': unittest.main()
