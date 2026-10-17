"""网络体检：小请求 / 大请求（POST 5MB）能不能过——微信客户端发图失败的可疑方向之一。"""
import time, urllib.request

def try_get(url, timeout=15):
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = r.read(2048)
        print("GET  %-38s ok %dB %.1fs" % (url[:38], len(data), time.time() - t0))
        return True
    except Exception as e:
        print("GET  %-38s FAIL %s %s" % (url[:38], type(e).__name__, str(e)[:60]))
        return False

def try_post(url, size_mb=5, timeout=60):
    body = b'x' * (size_mb * 1024 * 1024)
    t0 = time.time()
    req = urllib.request.Request(url, data=body, method='POST',
                                headers={'Content-Type': 'application/octet-stream'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            got = r.read(512)
        print("POST %5dMB %-30s ok %dB %.1fs" % (size_mb, url[:30], len(got), time.time() - t0))
        return True
    except Exception as e:
        print("POST %5dMB %-30s FAIL %s %s" % (size_mb, url[:30], type(e).__name__, str(e)[:80]))
        return False

try_get("https://www.baidu.com")
try_get("https://api.stepfun.com")
try_post("https://httpbin.org/post", 1, 45)
try_post("https://httpbin.org/post", 5, 60)
