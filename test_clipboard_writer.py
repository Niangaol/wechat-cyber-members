import sys, unittest, subprocess
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).parent/'src'))
from wechat_ui import WeChatUI, SafetyError

class ClipboardWriterTests(unittest.TestCase):
    def test_text_uses_pipe_detached_owner(self):
        ui=WeChatUI({'display': ':99'})
        process=Mock(returncode=0)
        with patch('wechat_ui.subprocess.Popen', return_value=process) as spawn:
            ui.clipboard_write('年糕')
        process.communicate.assert_called_once_with('年糕'.encode(), timeout=5)
        self.assertEqual(spawn.call_args.kwargs['stdout'], subprocess.DEVNULL)
        self.assertEqual(spawn.call_args.kwargs['stderr'], subprocess.DEVNULL)
        self.assertIn('UTF8_STRING', spawn.call_args.args[0])

    def test_failed_write_is_not_success(self):
        ui=WeChatUI({'display': ':99'})
        with patch('wechat_ui.subprocess.Popen', return_value=Mock(returncode=1)):
            with self.assertRaises(SafetyError): ui.clipboard_write('text')

if __name__=='__main__': unittest.main()
