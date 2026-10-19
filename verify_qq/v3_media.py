"""对抗式验证 3：media.fetch_image 的安全边界（契约 §5）。

全程离线：DNS 走 monkeypatch 替身、HTTP 走注入 opener；只有一个"负例"用
127.0.0.1 上的本地 HTTP 服务器，用来证明"本机地址被拒绝、且根本没发起连接"。
运行：python3 verify_qq/v3_media.py
"""
import hashlib
import http.server
import io
import os
import socket
import struct
import sys
import tempfile
import threading
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'verify_qq'))

from harness import group, check, eq, observe, run, summary      # noqa: E402
from qq.core import media                                        # noqa: E402
from web_reader import public_endpoint, WebSafetyError           # noqa: E402
from PIL import Image                                            # noqa: E402

PUBLIC_IP = '93.184.216.34'
TMP = tempfile.mkdtemp(prefix='verify-qq-media-')


def dest(name):
    path = Path(TMP) / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def real_png(w=8, h=8):
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (10, 20, 30)).save(buf, 'PNG')
    return buf.getvalue()


def real_gif():
    buf = io.BytesIO()
    Image.new('P', (4, 4)).save(buf, 'GIF')
    return buf.getvalue()


def real_jpeg():
    buf = io.BytesIO()
    Image.new('RGB', (4, 4)).save(buf, 'JPEG')
    return buf.getvalue()


def declared_png(width, height):
    """只带 IHDR/IEND 的 PNG：文件极小但声明了巨大尺寸（典型解压炸弹形态）。"""
    def chunk(tag, payload):
        return (struct.pack('>I', len(payload)) + tag + payload
                + struct.pack('>I', zlib.crc32(tag + payload) & 0xffffffff))
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(b'\x00' * 16)) + chunk(b'IEND', b''))


def opener_returning(status, headers=None, body=b''):
    def opener(url, *, ip, timeout_s=15, max_bytes=1 << 20):
        return status, dict(headers or {}), body
    return opener


def resolver_returning(host, port, ip):
    def resolver(url):
        from urllib.parse import urlsplit
        return urlsplit(url), host, port, ip
    return resolver


# ------------------------------------------------------- 1. DNS/私网（真实 public_endpoint）

def t_public_endpoint_rejects():
    bad = [
        'http://127.0.0.1/x.png', 'http://127.0.0.1:80/x.png',
        'http://localhost/x.png', 'http://[::1]/x.png',
        'http://0.0.0.0/x.png', 'http://10.0.0.1/x.png',
        'http://172.16.5.5/x.png', 'http://192.168.1.10/x.png',
        'http://169.254.169.254/latest/meta-data/',   # 云元数据
        'http://100.64.0.1/x.png',                    # CGNAT
        'http://240.0.0.1/x.png',                     # 保留
        'http://255.255.255.255/x.png',               # 广播
        'http://[fd00::1]/x.png',                     # ULA
        'http://[::ffff:127.0.0.1]/x.png',            # v4-mapped 回环
        'http://[fe80::1]/x.png',                     # 链路本地
        'http://224.0.0.1/x.png',                     # 组播（§10 D6）
        'http://239.255.255.250/x.png',               # SSDP 组播
        'http://[ff02::1]/x.png',                     # IPv6 链路本地组播
    ]
    for url in bad:
        try:
            public_endpoint(url)
            check('真实 resolver 必须拒绝 %s' % url, False, '竟然通过了')
        except WebSafetyError as exc:
            check('真实 resolver 拒绝 %s' % url, True, str(exc))
        except Exception as exc:
            check('真实 resolver 拒绝 %s（异常类型）' % url, False,
                  '%s: %s' % (type(exc).__name__, exc))


def t_public_endpoint_rejects_scheme_and_port():
    for url, why in [('ftp://example.com/x', 'scheme'),
                     ('file:///etc/passwd', 'scheme'),
                     ('http://user:pw@example.com/x', '凭据'),
                     ('http://example.com:8080/x', '端口'),
                     ('http://example.com:22/x', '端口'),
                     ('not-a-url', '格式')]:
        try:
            public_endpoint(url)
            check('真实 resolver 必须拒绝（%s）%s' % (why, url), False, '竟然通过了')
        except WebSafetyError as exc:
            check('真实 resolver 拒绝（%s）%s' % (why, url), True, str(exc))
        except Exception as exc:
            check('真实 resolver 拒绝（%s）%s' % (why, url), False,
                  '非 WebSafetyError：%s' % type(exc).__name__)


def t_port_zero_rejected():
    """契约 §10 D7：端口写成 0 必须直接拒，不能靠 \`p.port or 80\` 折成 80。"""
    from urllib.parse import urlsplit
    eq('前提：urlsplit 对 :0 给出 0（不是 None）',
       urlsplit('http://example.com:0/x').port, 0)
    for url in ('http://example.com:0/x', 'https://example.com:0/x',
                'http://example.com:0/x.png'):
        try:
            public_endpoint(url)
            check('端口 0 必须拒绝：%s' % url, False, '竟然通过了')
        except WebSafetyError as exc:
            check('端口 0 被拒绝：%s' % url, True, str(exc))
    eq('端口 0 在 fetch_image 上也是 None',
       media.fetch_image('http://example.com:0/x.png', dest('port0')), None)


def t_multicast_rejected():
    """契约 §10 D6：is_global 对组播是 True，必须显式挡 is_multicast / is_reserved。"""
    import ipaddress
    eq('前提：224.0.0.1 的 is_global 确实是 True（所以只看它会漏）',
       ipaddress.ip_address('224.0.0.1').is_global, True)
    eq('前提：224.0.0.1 的 is_multicast 是 True',
       ipaddress.ip_address('224.0.0.1').is_multicast, True)
    for url in ('http://224.0.0.1/x.png', 'http://239.255.255.250/x.png',
                'http://233.1.2.3/x.png', 'http://[ff02::1]/x.png',
                'http://[ff00::1]/x.png'):
        try:
            public_endpoint(url)
            check('组播地址必须拒绝：%s' % url, False, '竟然通过了')
        except WebSafetyError as exc:
            check('组播地址被拒绝：%s' % url, True, str(exc))
    for url in ('http://240.0.0.1/x.png', 'http://255.255.255.255/x.png'):
        try:
            public_endpoint(url)
            check('保留地址必须拒绝：%s' % url, False, '竟然通过了')
        except WebSafetyError as exc:
            check('保留地址被拒绝：%s' % url, True, str(exc))
    # 对照：真公网地址仍要放行，否则上面可能是"全拒"造成的假阳性
    parts, host, port, ip = public_endpoint('http://93.184.216.34/x.png')
    eq('对照：公网地址仍然放行', ip, '93.184.216.34')
    eq('对照：公网地址的端口解析正确', port, 80)
    eq('fetch_image 对组播地址返回 None',
       media.fetch_image('http://224.0.0.1/x.png', dest('mcast')), None)


def t_mixed_dns_rejected():
    """混合解析：公网 + 私网 必须整体拒绝（真实 public_endpoint + 打桩 getaddrinfo）。"""
    original = socket.getaddrinfo

    def fake(host, port, *a, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (PUBLIC_IP, port)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port))]

    socket.getaddrinfo = fake
    try:
        try:
            public_endpoint('http://mixed.example.com/x.png')
            check('混合 DNS（公网+私网）必须拒绝', False, '竟然通过了')
        except WebSafetyError as exc:
            check('混合 DNS（公网+私网）必须拒绝', True, str(exc))
        # 纯公网：应放行
        socket.getaddrinfo = lambda host, port, *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', (PUBLIC_IP, port))]
        parts, host, port, ip = public_endpoint('http://ok.example.com/x.png')
        eq('纯公网 DNS 放行并固定到该 IP', (host, port, ip), ('ok.example.com', 80, PUBLIC_IP))
        # DNS 无结果
        socket.getaddrinfo = lambda host, port, *a, **kw: []
        try:
            public_endpoint('http://empty.example.com/x.png')
            check('DNS 无结果必须拒绝', False, '竟然通过了')
        except WebSafetyError as exc:
            check('DNS 无结果必须拒绝', True, str(exc))
    finally:
        socket.getaddrinfo = original


def t_no_connection_when_rejected():
    """被拒绝时绝不能已经发起过 TCP 连接。"""
    original = socket.create_connection
    calls = []

    def spy(address, timeout=None, source_address=None):
        calls.append(address)
        raise AssertionError('不该发起连接')

    socket.create_connection = spy
    try:
        for url in ('http://127.0.0.1/x.png', 'http://localhost/x.png',
                    'http://10.1.1.1/x.png', 'http://example.com:8080/x.png'):
            result = media.fetch_image(url, dest('noconn'))
            eq('拒绝 + 返回 None：%s' % url, result, None)
    finally:
        socket.create_connection = original
    eq('被拒绝的链接一次 TCP 连接都没发起', calls, [])


def t_local_server_negative():
    """允许的负例：真起一个 127.0.0.1 上的 HTTP 服务器，验证请求根本到不了它。"""
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.end_headers()
            self.wfile.write(real_png())

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for host in ('127.0.0.1', 'localhost'):
            result = media.fetch_image('http://%s:%d/x.png' % (host, port),
                                       dest('localserver'))
            eq('本机地址（%s:%d）必须被拒绝' % (host, port), result, None)
        eq('被拒绝的本机请求一次都没打到服务器上', hits, [])
        # 对照组：手工绕过校验直接请求，证明服务器本身是活的（否则上面是假阳性）
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:%d/x.png' % port, timeout=5) as resp:
            alive = resp.status == 200 and resp.read()[:4] == b'\x89PNG'[:4]
        check('对照组：本地服务器确实可用（证明上面的拒绝不是假阳性）', alive)
    finally:
        server.shutdown()
        server.server_close()


# ------------------------------------------------------- 2. 跳转

def t_redirect_to_private():
    """第一跳公网 → 302 到私网：第二跳必须重新校验并拒绝。"""
    def opener(url, *, ip, timeout_s=15, max_bytes=1 << 20):
        return 302, {'location': 'http://127.0.0.1/evil.png'}, b''

    result = media.fetch_image('http://pub.example.com/a.png', dest('redir1'),
                               opener=opener,
                               resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP))
    eq('跳转链上出现私网 ip 时返回 None', result, None)


def t_redirect_chain_real_resolver():
    """真实 resolver：第一跳合法 DNS，跳转目标指向 127.0.0.1。"""
    original = socket.getaddrinfo

    def fake(host, port, *a, **kw):
        if host == 'pub.example.com':
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (PUBLIC_IP, port))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port))]

    socket.getaddrinfo = fake
    tried = []

    def opener(url, *, ip, timeout_s=15, max_bytes=1 << 20):
        tried.append((url, ip))
        return 302, {'location': 'http://inner.example.com/x.png'}, b''

    try:
        result = media.fetch_image('http://pub.example.com/a.png', dest('redir2'),
                                   opener=opener)
        eq('跳转进私网 → None', result, None)
        eq('第一跳确实连的是公网 IP', tried[0][1] if tried else None, PUBLIC_IP)
        eq('第二跳没有被发起（在校验阶段就被拒）', len(tried), 1)
    finally:
        socket.getaddrinfo = original


def t_redirect_too_many():
    def opener(url, *, ip, timeout_s=15, max_bytes=1 << 20):
        return 302, {'location': 'http://pub.example.com/next.png'}, b''

    result = media.fetch_image('http://pub.example.com/a.png', dest('redir3'),
                               opener=opener,
                               resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP))
    eq('无限跳转 → None（最多 4 跳）', result, None)


def t_redirect_no_location():
    result = media.fetch_image('http://pub.example.com/a.png', dest('redir4'),
                               opener=opener_returning(302, {}),
                               resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP))
    eq('302 但没有 Location → None', result, None)


# ------------------------------------------------------- 3. 端口

def t_port_check():
    for port in (8080, 22, 8443, 0, 65535):
        result = media.fetch_image(
            'http://pub.example.com:%d/a.png' % port if port else 'http://pub.example.com/a.png',
            dest('port'),
            opener=opener_returning(200, {}, real_png()),
            resolver=resolver_returning('pub.example.com', port, PUBLIC_IP))
        eq('端口 %d 必须拒绝' % port, result, None)
    for port in (80, 443):
        result = media.fetch_image(
            'http://pub.example.com/a.png', dest('port_ok'),
            opener=opener_returning(200, {'content-type': 'image/png'}, real_png()),
            resolver=resolver_returning('pub.example.com', port, PUBLIC_IP))
        check('端口 %d 放行' % port, result is not None and Path(result).is_file(),
              'result=%r' % result)


# ------------------------------------------------------- 4. 大小 / 魔数 / 像素

def t_size_limits():
    png = real_png()
    result = media.fetch_image('http://pub.example.com/a.png', dest('size1'),
                               max_bytes=len(png) - 1,
                               opener=opener_returning(200, {}, png),
                               resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP))
    eq('响应体超过 max_bytes → None', result, None)
    # 注入的 opener 绕过 _default_opener，所以这里只能证明"响应体本身"被拦；
    # content-length 的拦截在 _default_opener 里，由 t_default_opener_caps_read 覆盖。
    big = png + b'\x00' * (64 * 1024)
    result2 = media.fetch_image('http://pub.example.com/a.png', dest('size2'),
                                max_bytes=1024,
                                opener=opener_returning(200, {}, big),
                                resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP))
    eq('响应体超过 max_bytes（注入 opener 返回真超长 body）→ None', result2, None)
    eq('超长响应体没有落盘', list(dest('size2').iterdir()), [])


def t_default_opener_caps_read():
    """_default_opener 用 read(max_bytes+1) 封顶——用本地 socket 证明读取被截断。"""
    body = real_png()
    big = body + b'\x00' * (200 * 1024)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.end_headers()
            self.wfile.write(big)

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, headers, got = media._default_opener(
            'http://127.0.0.1:%d/x.png' % port, ip='127.0.0.1',
            timeout_s=5, max_bytes=4096)
        check('_default_opener 读取被 max_bytes+1 封顶',
              len(got) <= 4097, 'len=%d' % len(got))
    finally:
        server.shutdown()
        server.server_close()

    # content-length 预检：声明超大时直接放弃，body 一个字都不读
    class HugeHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Length', str(1 << 30))
            self.end_headers()
            try:
                self.wfile.write(b'\x00' * 4096)
            except Exception:
                pass

        def log_message(self, *a):
            pass

    server2 = http.server.HTTPServer(('127.0.0.1', 0), HugeHandler)
    port2 = server2.server_address[1]
    threading.Thread(target=server2.serve_forever, daemon=True).start()
    try:
        status2, headers2, got2 = media._default_opener(
            'http://127.0.0.1:%d/x.png' % port2, ip='127.0.0.1',
            timeout_s=5, max_bytes=4096)
        eq('content-length 超限时 body 直接返回空（预检拦下）', got2, b'')
        check('content-length 超限时 status 已被识别', status2 == 200, 'status=%r' % status2)
    finally:
        server.shutdown()
        server.server_close()


def t_magic_and_decode():
    cases = [
        ('纯文本冒充图片', b'hello world, not an image'),
        ('空响应体', b''),
        ('假 PNG 头 + 垃圾', b'\x89PNG\r\n\x1a\n' + b'\x00' * 64),
        ('假 GIF 魔数', b'GIF89a' + b'\x00' * 64),
        ('假 JPEG 魔数', b'\xff\xd8\xff' + b'\x00' * 64),
        ('假 WEBP 魔数', b'RIFF' + b'\x00\x00\x00\x00' + b'WEBP' + b'\x00' * 64),
        ('PDF 伪装成 png 扩展名', b'%PDF-1.4\n' + b'x' * 32),
        ('ZIP', b'PK\x03\x04' + b'\x00' * 32),
    ]
    for name, body in cases:
        result = media.fetch_image('http://pub.example.com/a.png', dest('magic'),
                                   opener=opener_returning(200, {}, body),
                                   resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP))
        eq('%s → None' % name, result, None)


def t_pixel_bomb():
    """像素炸弹：20MP 以上必须拒（PIL 自己的阈值是 89M，挡不住 24MP）。"""
    for w, h, label in ((6000, 4000, '24MP（PIL 阈值以下，只能靠我们的 20MP 上限）'),
                        (20000, 20000, '400MP（PIL DecompressionBombError 区间）'),
                        (5000, 5000, '25MP')):
        body = declared_png(w, h)
        result = media.fetch_image('http://pub.example.com/bomb.png', dest('bomb'),
                                   opener=opener_returning(200, {}, body),
                                   resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP))
        eq('%dx%d %s → None' % (w, h, label), result, None)
    # 边界：正好 20MP 未超限（但我们的图是残缺的，verify() 会失败 → 仍 None）
    check('MAX_PIXELS 常量', media.MAX_PIXELS == 20 * 1000 * 1000, str(media.MAX_PIXELS))
    eq('宽或高为 0 → None', media.fetch_image(
        'http://pub.example.com/z.png', dest('zero'),
        opener=opener_returning(200, {}, declared_png(0, 100)),
        resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP)), None)


def t_http_status():
    for status in (204, 301 + 100, 400, 403, 404, 500, 502, 302):
        result = media.fetch_image('http://pub.example.com/a.png', dest('status'),
                                   opener=opener_returning(status, {}, real_png()),
                                   resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP))
        eq('HTTP %d → None' % status, result, None)


# ------------------------------------------------------- 5. 成功路径 / 落盘

def t_success_and_permissions():
    png = real_png()
    target_dir = dest('ok')
    result = media.fetch_image('http://pub.example.com/a.png', target_dir,
                               opener=opener_returning(200, {'content-type': 'image/png'}, png),
                               resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP))
    check('合法 PNG → 返回 Path', isinstance(result, Path) and result.is_file(), repr(result))
    expect_name = hashlib.sha256(png).hexdigest()[:16] + '.png'
    eq('落盘文件名 = sha256 前 16 位 + .png', Path(result).name, expect_name)
    eq('文件内容一致', Path(result).read_bytes(), png)
    eq('文件权限 600', oct(os.stat(result).st_mode & 0o777), '0o600')
    eq('目录权限 700', oct(os.stat(target_dir).st_mode & 0o777), '0o700')
    for body, ext in ((real_gif(), 'gif'), (real_jpeg(), 'jpg')):
        r = media.fetch_image('http://pub.example.com/a.bin', dest('ok2'),
                              opener=opener_returning(200, {}, body),
                              resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP))
        eq('魔数识别 %s（与 URL 扩展名无关）' % ext,
           Path(r).suffix, '.' + ext)


def t_dedupe_by_content():
    png = real_png()
    d = dest('dedupe')
    a = media.fetch_image('http://pub.example.com/1.png', d,
                          opener=opener_returning(200, {}, png),
                          resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP))
    b = media.fetch_image('http://pub.example.com/2.png', d,
                          opener=opener_returning(200, {}, png),
                          resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP))
    eq('相同内容落到同一个文件名（天然去重）', str(a), str(b))
    eq('目录里只有一个文件', len(list(d.iterdir())), 1)


def t_no_leftover_tmp():
    png = real_png()
    d = dest('tmp')
    media.fetch_image('http://pub.example.com/a.png', d,
                      opener=opener_returning(200, {}, png),
                      resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP))
    left = [p.name for p in d.iterdir() if p.name.startswith('.')]
    eq('成功后不留 .tmp 临时文件', left, [])


# ------------------------------------------------------- 6. 绝不抛异常

def t_never_raises():
    class Boom(Exception):
        pass

    def bad_opener(url, *, ip, timeout_s=15, max_bytes=0):
        raise Boom('网络炸了')

    def bad_resolver(url):
        raise Boom('DNS 炸了')

    eq('opener 抛任意异常 → None', media.fetch_image(
        'http://pub.example.com/a.png', dest('boom'), opener=bad_opener,
        resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP)), None)
    eq('resolver 抛任意异常 → None', media.fetch_image(
        'http://pub.example.com/a.png', dest('boom'), resolver=bad_resolver), None)
    eq('resolver 返回垃圾（None）→ None', media.fetch_image(
        'http://pub.example.com/a.png', dest('boom'),
        opener=opener_returning(200, {}, real_png()),
        resolver=lambda url: None), None)
    eq('resolver 返回字段不足 → None', media.fetch_image(
        'http://pub.example.com/a.png', dest('boom'),
        opener=opener_returning(200, {}, real_png()),
        resolver=lambda url: ('x', 'y')), None)
    for bad_url in (None, '', '   ', 123, b'bytes', 'http://', 'http:///x',
                    'javascript:alert(1)', 'data:image/png;base64,AAAA'):
        try:
            result = media.fetch_image(bad_url, dest('boom'))
            check('坏 url %r → None 且不抛' % (bad_url,), result is None, 'result=%r' % result)
        except Exception as exc:
            check('坏 url %r → None 且不抛' % (bad_url,), False,
                  '%s: %s' % (type(exc).__name__, exc))
    lucky = media.fetch_image('http://pub.example.com/a.png', '/proc/不可写/x',
                              opener=opener_returning(200, {}, real_png()),
                              resolver=resolver_returning('pub.example.com', 80, PUBLIC_IP))
    eq('落盘目录不可写 → None（不抛）', lucky, None)


def t_introspection_contract():
    import inspect
    for name, fn in (('fetch_image', media.fetch_image),
                     ('within_event_limit', media.within_event_limit)):
        params = inspect.signature(fn).parameters
        check('%s 可注入 opener/resolver 或 max_images' % name,
              name == 'fetch_image' and {'opener', 'resolver'} <= set(params)
              or name == 'within_event_limit' and 'max_images' in params,
              str(list(params)))


def t_within_event_limit():
    class E:
        images = [{'url': 'http://a/1.png'}, {'url': ''}, 'http://a/2.png',
                  {'file': 'no-url'}, {'url': 'http://a/3.png'}, 42, None]
    eq('取前 2 个有效 url', media.within_event_limit(E(), 2),
       ['http://a/1.png', 'http://a/2.png'])
    eq('max_images=0 → 空', media.within_event_limit(E(), 0), [])
    eq('max_images 是坏类型 → 空', media.within_event_limit(E(), 'x'), [])
    eq('max_images 是 None → 空', media.within_event_limit(E(), None), [])
    eq('max_images 负数 → 空', media.within_event_limit(E(), -3), [])

    class NoImages:
        pass
    eq('event 没有 images 属性 → 空', media.within_event_limit(NoImages(), 2), [])
    eq('event=None → 空', media.within_event_limit(None, 2), [])


def t_safe_url_strips_query():
    got = media._safe_url('https://evil.example.com/p/a.png?token=SECRET123&x=1')
    check('日志用链接去掉查询串（不泄露鉴权参数）',
          'SECRET123' not in got and got == 'https://evil.example.com/p/a.png', got)


group('§5 私网/本机/混合 DNS（真实 web_reader.public_endpoint）')
for fn in (t_public_endpoint_rejects, t_public_endpoint_rejects_scheme_and_port,
           t_port_zero_rejected, t_multicast_rejected, t_mixed_dns_rejected,
           t_no_connection_when_rejected, t_local_server_negative):
    run(fn)

group('§5 跳转逐跳重校验')
for fn in (t_redirect_to_private, t_redirect_chain_real_resolver,
           t_redirect_too_many, t_redirect_no_location):
    run(fn)

group('§5 端口 80/443')
for fn in (t_port_check,):
    run(fn)

group('§5 大小 / 魔数 / 像素炸弹')
for fn in (t_size_limits, t_default_opener_caps_read, t_magic_and_decode,
           t_pixel_bomb, t_http_status):
    run(fn)

group('§5 成功路径与落盘权限')
for fn in (t_success_and_permissions, t_dedupe_by_content, t_no_leftover_tmp):
    run(fn)

group('§5 任何失败返回 None、绝不抛给调用方')
for fn in (t_never_raises, t_introspection_contract, t_within_event_limit,
           t_safe_url_strips_query):
    run(fn)

summary('media 验证')
