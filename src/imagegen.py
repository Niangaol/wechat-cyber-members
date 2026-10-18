"""千问平台生图：qwen-image-2.1-turbo。仅文字入、图片文件出；不发送任何图片到聊天。"""
import base64, binascii, json, os, re, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = Path.home()/'.local'/'state'/'wechat-bot'
OC_REF = ROOT/'config'/'assets'/'oc-reference.png'   # 年糕.Agent OC 参考图

PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
JPEG_MAGIC = b'\xff\xd8\xff'
MAX_BYTES = 20 * 1024 * 1024
REF_IMAGE_MAX = 512          # 参考图缩放上限（边长像素），控制 base64 体积
REF_IMAGE_MAX_BYTES = 2 * 1024 * 1024

class ImageGenError(RuntimeError): pass

def _key(state_dir=None, credentials_file=None):
    # credentials_file 优先（可给绝对路径，共享微信那份 600 凭据）；否则按 state_dir 找。
    if credentials_file:
        p = Path(credentials_file)
    else:
        p = (Path(state_dir) if state_dir else STATE)/'credentials.json'
    if p.exists():
        return json.loads(p.read_text()).get('image_gen_api_key', '')
    return ''

def _post(url, payload, key, timeout=180):
    req = urllib.request.Request(url, json.dumps(payload, ensure_ascii=False).encode(),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read(2 * 1024 * 1024 + 1))

def _get(url, key, timeout=60):
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read(2 * 1024 * 1024 + 1))

def _extract(data):
    """从 multimodal-generation 响应中抠图片：支持 message.content 数组里的 image 字段"""
    choices = (data.get('output') or {}).get('choices') or []
    if not choices:
        raise ImageGenError('响应无 choices')
    content = (choices[0].get('message') or {}).get('content')
    if not isinstance(content, list):
        raise ImageGenError('响应无 content 数组')
    for item in content:
        if isinstance(item, dict) and item.get('image'):
            return item['image']
    raise ImageGenError('content 中无 image 字段')

def _decode(image_ref, out_dir):
    """image 可能是 URL 或 data:base64；下载/解码后校验 magic bytes"""
    out_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(image_ref, str) and image_ref.startswith('data:'):
        m = re.match(r'data:image/(png|jpeg);base64,(.+)', image_ref, re.S)
        if not m:
            raise ImageGenError('不支持的 data URL 格式')
        raw = base64.b64decode(m.group(2), validate=True)
        ext = m.group(1)
    elif isinstance(image_ref, str) and image_ref.startswith('http'):
        req = urllib.request.Request(image_ref, headers={'User-Agent': 'curl/8'})
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read(MAX_BYTES + 1)
        ext = 'png' if image_ref.lower().endswith('.png') else 'jpg'
    else:
        raise ImageGenError('无法识别的图片字段')
    if len(raw) > MAX_BYTES:
        raise ImageGenError('图片超过大小上限')
    if raw.startswith(PNG_MAGIC):
        ext = 'png'
    elif raw.startswith(JPEG_MAGIC):
        ext = 'jpg'
    else:
        raise ImageGenError('文件头不是 PNG/JPEG')
    out = out_dir/('gen-%d.%s' % (int(time.time()), ext))
    out.write_bytes(raw)
    os.chmod(out, 0o600)
    return out

def _ref_image_part(path):
    """把参考图读成多模态 content 片段：{'image': 'data:image/png;base64,...'}。

    缩放到 REF_IMAGE_MAX 以内；读不了/超大就返回 None（调用方退回纯文字）。
    """
    p = Path(path)
    if not p.exists() or p.stat().st_size > REF_IMAGE_MAX_BYTES:
        return None
    try:
        from PIL import Image
        import io
        im = Image.open(p).convert('RGB')
        if max(im.size) > REF_IMAGE_MAX:
            im.thumbnail((REF_IMAGE_MAX, REF_IMAGE_MAX), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, 'PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None
    return {'image': 'data:image/png;base64,' + b64}


def oc_prefix():
    """OC 人设外观描述（生图提示词前缀）。文件缺失时返回内置精简版。"""
    p = ROOT / 'config' / 'assets' / 'oc-character.md'
    try:
        text = p.read_text(encoding='utf-8')
        seg = text.split('## 角色外观', 1)[1].split('##', 1)[0]
        lines = [l.strip() for l in seg.splitlines()
                 if l.strip() and not l.strip().startswith('（')]
        return ' '.join(lines)
    except Exception:
        return ('奶白色方形年糕（右上角有咬痕），宽檐绿色探险帽配金色帽徽，'
                '绿色大眼睛，两颊红晕，蓝色双肩背包插铺盖卷，黄色探险靴，'
                '像素艺术风格，暖色调，治愈系，画面干净无文字')


def generate(prompt, base='https://maas.qianwenaiapi.com', model='qwen-image-2.1-turbo',
             ref_image=None, state_dir=None, credentials_file=None):
    """文生图（可带 OC 参考图）。返回本地文件路径。同步响应直接用；task_id 响应则轮询。

    ref_image 传入时会把图缩到 512px 内以 base64 data URL 放进 content 数组最前面；
    API 不支持图片输入时会报错，由调用方决定是否退回纯文字重试。
    """
    key = _key(state_dir, credentials_file)
    media_dir = (Path(state_dir) if state_dir else STATE)/'media'
    if not key:
        raise ImageGenError('生图 Key 未配置')
    if not isinstance(prompt, str) or not prompt.strip():
        raise ImageGenError('提示词为空')
    if len(prompt) > 4000:
        raise ImageGenError('提示词超长')
    content = [{'text': prompt[:4000]}]
    if ref_image:
        part = _ref_image_part(ref_image)
        if part:
            content.insert(0, part)   # 图在前，文字指令在后
    payload = {'model': model,
               'input': {'messages': [{'role': 'user', 'content': content}]},
               'parameters': {'prompt_extend': True}}
    data = _post(base.rstrip('/') + '/api/v1/services/aigc/multimodal-generation/generation', payload, key)
    # 异步任务形态
    task_id = (data.get('output') or {}).get('task_id')
    if task_id and not (data.get('output') or {}).get('choices'):
        deadline = time.time() + 300
        while time.time() < deadline:
            time.sleep(5)
            t = _get(base.rstrip('/') + '/api/v1/tasks/' + task_id, key)
            status = (t.get('output') or {}).get('task_status')
            if status == 'SUCCEEDED':
                return _decode(_extract(t), media_dir)
            if status in ('FAILED', 'CANCELED', 'UNKNOWN'):
                raise ImageGenError('生图任务状态 ' + str(status))
        raise ImageGenError('生图轮询超时')
    return _decode(_extract(data), media_dir)

if __name__ == '__main__':
    import sys
    try:
        p = generate(sys.argv[1] if len(sys.argv) > 1 else '一只橘色小猫坐在窗台上，午后阳光，写实风格')
        print('GEN_OK', p, p.stat().st_size, 'bytes')
    except Exception as e:
        print('GEN_FAIL', type(e).__name__, str(e)[:200])
