import sys, ipaddress, socket
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from web_reader import public_endpoint, WebSafetyError

print('--- ipaddress 语义 ---')
for ip in ('224.0.0.1', '239.255.255.250', '240.0.0.1', '255.255.255.255',
           '100.64.0.1', '192.0.2.1', '198.18.0.1', '0.0.0.0'):
    a = ipaddress.ip_address(ip)
    print('%-18s is_global=%-5s is_private=%-5s is_multicast=%-5s is_reserved=%s'
          % (ip, a.is_global, a.is_private, a.is_multicast, a.is_reserved))

print('--- public_endpoint ---')
for url in ('http://224.0.0.1/x.png', 'http://239.255.255.250/x.png',
            'http://255.255.255.255/x.png', 'http://240.0.0.1/x.png'):
    try:
        got = public_endpoint(url)
        print('%-32s 通过 -> %r' % (url, got[3]))
    except WebSafetyError as e:
        print('%-32s 拒绝 WebSafetyError: %s' % (url, e))
    except Exception as e:
        print('%-32s 其它异常 %s: %s' % (url, type(e).__name__, e))

print('--- 端口 0 的 or 语义 ---')
from urllib.parse import urlsplit
for u in ('http://example.com:0/x', 'https://example.com:0/x', 'http://example.com/x'):
    p = urlsplit(u)
    print('%-30s p.port=%r  -> 实际用 %r' % (u, p.port, p.port or (443 if p.scheme == 'https' else 80)))
