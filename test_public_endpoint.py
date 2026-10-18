"""public_endpoint 的安全边界（微信侧链接阅读与 QQ 侧图片下载共用这一份校验）。

背景（独立验证 qq-verifier 发现）：Python 里 224.0.0.1 的 is_global 竟然是 True，
只看 is_global 会放行 224/4（IPv6 的 ff00::/8 同理）；另外 p.port or 80 会把显式的 :0 折成 80。
这两条都被修掉并在这里钉死。用例全部在 DNS 之前就抛错，所以离线可跑、不出网。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import web_reader                                                   # noqa: E402


class PublicEndpointGuardTests(unittest.TestCase):
    def assert_rejected(self, url):
        with self.assertRaises(web_reader.WebSafetyError):
            web_reader.public_endpoint(url)

    def test_private_and_loopback_rejected(self):
        for url in ("http://127.0.0.1/x", "http://10.1.2.3/x", "http://192.168.1.1/x",
                    "http://[::1]/x", "http://0.0.0.0/x"):
            self.assert_rejected(url)

    def test_multicast_and_reserved_rejected(self):
        for url in ("http://224.0.0.1/x.png", "http://239.1.2.3/x", "http://240.0.0.1/x",
                    "http://[ff02::1]/x"):
            self.assert_rejected(url)

    def test_port_zero_is_not_defaulted_to_80(self):
        self.assert_rejected("http://example.com:0/x")

    def test_non_standard_port_and_scheme_rejected(self):
        for url in ("http://example.com:8080/x", "https://example.com:22/x",
                    "ftp://example.com/x", "http://user:pw@example.com/x"):
            self.assert_rejected(url)


if __name__ == "__main__":
    unittest.main()
