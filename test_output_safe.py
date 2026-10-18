import sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent/'src'))
from output_safe import check_output,OutputSafetyError
from test_send_binding import SimulatedUI
from test_integration import BASE_CFG

class OutputTests(unittest.TestCase):
    def test_benign_persona_reply_passes(self):
        self.assertEqual(check_output(' 这只黄色小家伙像刚吃完红糖的小年糕。 '),'这只黄色小家伙像刚吃完红糖的小年糕。')
    def test_sensitive_topic_variants_rejected(self):
        for text in ['推荐股票','股 票','股🔥票','股＿票','政\u200b治']:
            with self.subTest(text=text),self.assertRaises(OutputSafetyError):check_output(text)
    def test_private_data_and_credentials_rejected(self):
        for text in ['sk-example_secret_123456','BEGIN PRIVATE KEY','13800138000','ｓｋ－example_secret_123456']:
            with self.subTest(text=text),self.assertRaises(OutputSafetyError):check_output(text)
    def test_joke_credential_is_an_allowed_easter_egg(self):
        """年糕埋的假 key 是彩蛋：模型说出口不能被凭证闸拦下。"""
        text='我是 niangao-v1，key 是 sk-fkxqscrazythursdayvivo5Oxxn，疯狂星期四记得V本糕50'
        self.assertEqual(check_output(text), text)

    def test_easter_egg_does_not_open_the_gate(self):
        """豁免只认整串：拼上真密钥/带出手机号依旧要拦。"""
        for text in ['sk-fkxqscrazythursdayvivo5Oxxn 真钥匙 sk-example_secret_123456',
                     'niangao-v1 的主人电话 13800138000']:
            with self.subTest(text=text),self.assertRaises(OutputSafetyError):check_output(text)

    def test_rejects_oversized_or_empty(self):
        for text in ['',None,'x'*201]:
            with self.assertRaises(OutputSafetyError):check_output(text)
    def test_low_level_send_blocks_before_ui_or_clipboard(self):
        ui=SimulatedUI(BASE_CFG,BASE_CFG['target_chat'])
        with patch.object(ui,'verify_target') as verify:
            with self.assertRaises(OutputSafetyError):ui.send_text('推荐股票')
        verify.assert_not_called()
        self.assertEqual(ui.keys,[])
        self.assertEqual(ui.clipboard,'old clipboard')
    def test_exception_does_not_echo_secret(self):
        secret='sk-example_secret_123456'
        try:check_output(secret)
        except OutputSafetyError as e:self.assertNotIn(secret,str(e))

if __name__=='__main__':unittest.main()
