"""受限图片下载（契约 v1 · 第 5 节）。

这是**唯一**允许发起网络下载的地方，安全性照抄 src/web_reader.py 的思路：
1. 只允许无凭据的 http/https、端口 80/443；
2. DNS 解析出来的**所有**地址都必须是公网地址（私网/本机/保留地址/混合解析一律拒）；
3. 连接固定到刚才校验过的那个 IP（TLS 仍校验原 hostname），避免 DNS 重绑定；
4. 跳转逐次重新校验（最多 4 跳），不跟着跳到内网去；
5. 魔数 + PIL verify() + 像素上限三重校验；
6. 落盘用内容哈希命名、权限 600，先写临时文件再原子替换。

**任何失败都返回 None 并写日志，绝不把异常抛给调用方**——一张图下不下来，
不该让整条回复失败。
"""
import hashlib
import http.client
import io
import logging
import os
import socket
from pathlib import Path
from urllib.parse import urlsplit, urljoin

from web_reader import public_endpoint, WebSafetyError

MAX_BYTES = 10 * 1024 * 1024
TIMEOUT_S = 15
MAX_PIXELS = 20 * 1000 * 1000       # 2000 万像素，挡住解压炸弹
MAX_REDIRECTS = 4
ALLOWED_PORTS = (80, 443)
USER_AGENT = 'QQBot-ReadOnly/1.0'


class MediaError(ValueError):
    """图片下载/校验不通过。只在模块内部流转，对外一律是 None。"""


def _sniff(raw):
    """按魔数认格式：URL 里的扩展名是外部数据，不能信。"""
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if raw.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if raw[:6] in (b'GIF87a', b'GIF89a'):
        return 'gif'
    if len(raw) >= 12 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        return 'webp'
    return ''


def _verify_image(raw):
    """PIL 校验：先看尺寸（open 只读文件头，不解码像素），再 verify() 查完整性。"""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            width, height = probe.size
    except Exception as exc:                       # noqa: BLE001 外部字节什么都可能是
        raise MediaError('图片无法解码: %s' % type(exc).__name__) from exc
    if width <= 0 or height <= 0:
        raise MediaError('图片尺寸非法')
    if width * height > MAX_PIXELS:
        raise MediaError('像素超过上限(%d)' % MAX_PIXELS)
    try:
        with Image.open(io.BytesIO(raw)) as check:
            check.verify()
    except Exception as exc:                       # noqa: BLE001
        raise MediaError('图片校验失败: %s' % type(exc).__name__) from exc


def _header(headers, name):
    """大小写无关地取响应头。headers 可能是 dict 或 (key, value) 列表。"""
    wanted = str(name).lower()
    items = headers.items() if hasattr(headers, 'items') else (headers or [])
    for key, value in items:
        if str(key).lower() == wanted:
            return str(value or '')
    return ''


def _safe_url(url):
    """日志用的链接：去掉查询串（QQ 图片链接里带鉴权参数，不该进日志）。"""
    try:
        parts = urlsplit(str(url or ''))
        return '%s://%s%s' % (parts.scheme, parts.netloc, parts.path)
    except ValueError:
        return '<坏链接>'


def _default_opener(url, *, ip, timeout_s=TIMEOUT_S, max_bytes=MAX_BYTES):
    """单次 GET：把连接固定到已经校验过的 IP（防 DNS 重绑定）。→ (status, headers, body)"""
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == 'https' else 80)
    factory = (http.client.HTTPSConnection if parts.scheme == 'https'
               else http.client.HTTPConnection)
    connection = factory(parts.hostname, port=port, timeout=timeout_s)
    # 只换"连到哪个 IP"，TLS 握手仍用原 hostname 校验证书
    connection._create_connection = (
        lambda address, timeout=None, source_address=None:
        socket.create_connection((ip, port), timeout, source_address))
    try:
        path = parts.path or '/'
        if parts.query:
            path += '?' + parts.query
        connection.request('GET', path, headers={
            'User-Agent': USER_AGENT, 'Accept': 'image/*',
            'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        headers = {str(k).lower(): str(v or '') for k, v in response.getheaders()}
        if response.status != 200:
            return response.status, headers, b''
        length = headers.get('content-length') or ''
        if length.isdigit() and int(length) > max_bytes:
            return response.status, headers, b''
        return response.status, headers, response.read(max_bytes + 1)
    finally:
        connection.close()


def _store(raw, ext, dest_dir):
    """落盘：按内容哈希命名（重复图片天然复用），先写临时文件再原子替换。"""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(dest_dir, 0o700)
    except OSError:
        pass
    digest = hashlib.sha256(raw).hexdigest()[:16]
    target = dest_dir / ('%s.%s' % (digest, ext))
    temp = dest_dir / ('.%s.%s.tmp' % (digest, ext))
    temp.write_bytes(raw)
    os.chmod(temp, 0o600)
    temp.replace(target)
    return target


def within_event_limit(event, max_images=2):
    """取这条事件里前 N 个图片链接（去空、保序）。"""
    try:
        limit = max(0, int(max_images))
    except (TypeError, ValueError):
        limit = 0
    if not limit:
        return []
    urls = []
    for image in (getattr(event, 'images', None) or []):
        if isinstance(image, dict):
            url = str(image.get('url') or '')
        elif isinstance(image, str):
            url = image
        else:
            continue
        url = url.strip()
        if url:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def fetch_image(url, dest_dir, *, max_bytes=MAX_BYTES, timeout_s=TIMEOUT_S,
                opener=None, resolver=None):
    """下载一张图片到 dest_dir，返回本地 Path；任何失败返回 None。

    opener  : 可注入的单次请求替身（离线测试用），签名见 _default_opener；
    resolver: 可注入的地址校验替身，默认 web_reader.public_endpoint。
    """
    try:
        return _fetch(url, Path(dest_dir), int(max_bytes), float(timeout_s),
                      opener or _default_opener, resolver or public_endpoint)
    except (MediaError, WebSafetyError) as exc:
        logging.warning('qq_fetch_image_rejected url=%s reason=%s',
                        _safe_url(url), str(exc)[:120])
        return None
    except Exception as exc:                       # noqa: BLE001 下载失败不能拖垮回复
        logging.warning('qq_fetch_image_failed url=%s type=%s reason=%s',
                        _safe_url(url), type(exc).__name__, str(exc)[:120])
        return None


def _fetch(url, dest_dir, max_bytes, timeout_s, opener, resolver):
    current = str(url or '').strip()
    if not current:
        raise MediaError('空链接')
    for _ in range(MAX_REDIRECTS):
        parts, host, port, ip = resolver(current)      # 每次都重新校验（含跳转后）
        if port not in ALLOWED_PORTS:
            raise MediaError('禁止非标准端口')
        status, headers, body = opener(current, ip=ip, timeout_s=timeout_s,
                                       max_bytes=max_bytes)
        status = int(status)
        if status in (301, 302, 303, 307, 308):
            location = _header(headers, 'location')
            if not location:
                raise MediaError('无效跳转')
            current = urljoin(current, location)
            continue
        if status != 200:
            raise MediaError('图片返回 HTTP %d' % status)
        if len(body) > max_bytes:
            raise MediaError('超过大小上限')
        ext = _sniff(body)
        if not ext:
            raise MediaError('文件头不是 PNG/JPEG/GIF/WEBP')
        _verify_image(body)
        return _store(body, ext, dest_dir)
    raise MediaError('跳转次数超限')
