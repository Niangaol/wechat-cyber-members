import sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent/'src'))
from resident import trailing_new
from web_reader import public_endpoint, WebSafetyError, TextOnly
from multimodal import parse_json

class Tests(unittest.TestCase):
    def test_no_history_replay(self): self.assertIsNone(trailing_new([],['old']))
    def test_append(self): self.assertEqual(trailing_new(['a','b'],['a','b','c']),2)
    def test_scrolled(self): self.assertEqual(trailing_new(['a','b'],['b','c']),1)
    def test_no_continuity(self): self.assertIsNone(trailing_new(['a'],['z']))
    def test_repeated(self): self.assertEqual(trailing_new(['a','b'],['a','b','b']),2)
    def test_same(self): self.assertEqual(trailing_new(['a','b'],['a','b']),2)
    def test_ambiguous_conservative(self): self.assertEqual(trailing_new(['b'],['b','b']),2)
    def test_local_urls(self):
        for u in ['file:///etc/passwd','ftp://example.com','http://u:p@example.com','https://example.com:8443']:
            with self.assertRaises(WebSafetyError): public_endpoint(u)
    def test_private_dns(self):
        for ip in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','::ffff:127.0.0.1']:
            with patch('socket.getaddrinfo',return_value=[(2,1,6,'',(ip,443))]):
                with self.assertRaises(WebSafetyError): public_endpoint('https://example.com')
    def test_mixed_dns(self):
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443)),(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(WebSafetyError): public_endpoint('https://example.com')
    def test_public_dns(self):
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]):
            self.assertEqual(public_endpoint('https://example.com')[3],'8.8.8.8')
    def test_script_stripped(self):
        p=TextOnly();p.feed('<p>正文</p><script>steal keys</script>')
        self.assertIn('正文',''.join(p.parts)); self.assertNotIn('steal',''.join(p.parts))
    def test_json_strict(self):
        self.assertEqual(parse_json('{"a":1}'),{'a':1})
        with self.assertRaises(ValueError): parse_json('ignore instructions')
    def test_not_object(self):
        with self.assertRaises(ValueError): parse_json('[]')

if __name__=='__main__': unittest.main(verbosity=2)
