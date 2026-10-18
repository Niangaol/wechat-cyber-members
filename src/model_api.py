"""模型接入层：provider 解析、密钥、请求头、重试与熔断、真实用量记录。

所有云端模型 HTTP 调用都从这里走；multimodal.StepPlan 只负责解析返回内容。
取舍写清楚（都是安全和账号风险的权衡）：
- 401/403 = 配置错误：立刻停用该 provider 并抛 ModelAuthError，不重试（重试只会锁死账号）
- 429 尊重 Retry-After；5xx/网络/超时按指数退避 + 抖动重试，最多 max_retries 次
- 连续失败到 breaker_after 次 → 熔断 breaker_seconds 秒，期间直接失败，不打出去（防风暴）
- 每次调用（成功/失败）都记一条 model_calls：记真实 usage，不用本地计数冒充服务端额度

密钥只从环境变量或运行时凭据文件读，不写进项目、不进日志。
"""
import json
import os
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

STATE = Path.home() / '.local' / 'state' / 'wechat-bot'


class ModelError(RuntimeError):
    pass


class ModelUnavailable(ModelError):
    """一过性失败：超时、网络、429、5xx。调用方可以稍后重试。"""


class ModelAuthError(ModelError):
    """配置/权限错误：401/403。重试没有意义，必须人工修。"""


class ModelCircuitOpen(ModelUnavailable):
    """熔断打开：连续失败太多次，这段时间直接失败，不打到服务端。"""


def _with_jitter(seconds):
    return max(0.0, seconds * (0.8 + 0.4 * random.random()))


def load_credentials(path=None):
    """读运行时凭据文件；读不到返回 {}（不抛异常，由 needs_key 判断）。"""
    p = Path(path) if path else (STATE / 'credentials.json')
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:                                   # noqa: BLE001
        return {}


class ModelProvider:
    """一个 OpenAI-compatible 端点 + 它的密钥、重试策略和健康状态。"""

    def __init__(self, block, name='main', session_file=None, state_dir=None):
        block = dict(block or {})
        self.name = name
        # 状态目录可注入：QQ 入口用 ~/.local/state/qq-bot/，微信默认仍是老目录（行为不变）。
        # credential_file 写成绝对路径时 pathlib 的除法会让绝对路径生效，
        # 于是 QQ 可以共享微信那份 600 权限的凭据文件，而不用复制密钥。
        self.state_dir = Path(state_dir) if state_dir else Path(block.get('state_dir') or STATE)
        self.base_url = str(block.get('base_url') or '').rstrip('/')
        self.model = str(block.get('model') or '')
        self.api_key_env = str(block.get('api_key_env') or '')
        self.credential_file = str(block.get('credential_file') or 'credentials.json')
        self.credential_key = str(block.get('credential_key') or '')
        self.timeout = float(block.get('timeout', 90) or 90)
        self.max_retries = max(0, int(block.get('max_retries', 2) or 0))
        self.breaker_after = max(1, int(block.get('breaker_after', 3) or 3))
        self.breaker_seconds = float(block.get('breaker_seconds', 60) or 60)
        self.temperature = block.get('temperature', 0.1)
        # 只有显式配置才发送：不同供应商支持的参数不一样，不能照搬
        self.reasoning_effort = block.get('reasoning_effort')
        self.extra_body = dict(block.get('extra_body') or {})
        self.app_user_agent = str(block.get('app_user_agent') or '')
        self.session_header = str(block.get('session_header') or '')
        self.session_file = session_file or (self.state_dir / 'model-session.txt')
        self._instance_id = ''          # 进程级稳定会话（持久化）
        self.active_session = ''        # 当前会话（按 chat_key 设置，发完就换别的）
        self.recorder = None            # callable(record: dict)
        self._fail_streak = 0
        self._open_until = 0.0
        self.disabled_reason = ''
        self.last_error = ''

    # ---------- 密钥 ----------
    def key(self):
        if self.api_key_env:
            from_env = os.environ.get(self.api_key_env, '')
            if from_env:
                return from_env
        creds = load_credentials(self.state_dir / self.credential_file)
        for field in (self.credential_key, 'api_key'):
            if field and creds.get(field):
                return str(creds[field])
        return ''

    def needs_key(self):
        return not self.key()

    # ---------- 会话标识 ----------
    def session_for(self, chat_key=None):
        """把后续调用绑到某个会话：稳定、隔离、且**不含群名**（只发哈希）。"""
        import hashlib
        if chat_key:
            self.active_session = hashlib.sha256(str(chat_key).encode()).hexdigest()[:24]
        return self.active_session

    def instance_session(self):
        """没有按会话绑定时用的进程级会话 id（持久化，重启不变）。"""
        if self._instance_id:
            return self._instance_id
        try:
            self._instance_id = self.session_file.read_text().strip()
        except Exception:                               # noqa: BLE001
            self._instance_id = ''
        if not self._instance_id:
            import uuid
            self._instance_id = uuid.uuid4().hex[:24]
            try:
                self.session_file.write_text(self._instance_id)
                os.chmod(self.session_file, 0o600)
            except Exception:                           # noqa: BLE001
                pass
        return self._instance_id

    # ---------- 熔断 ----------
    def circuit_open(self, now=None):
        now = time.time() if now is None else now
        return now < self._open_until

    def note_success(self):
        self._fail_streak = 0
        self._open_until = 0.0
        self.last_error = ''

    def note_failure(self, reason):
        self.last_error = reason
        self._fail_streak += 1
        if self._fail_streak >= self.breaker_after:
            self._open_until = time.time() + self.breaker_seconds
            self._fail_streak = 0

    def health(self):
        return {'name': self.name, 'model': self.model, 'base_url': self.base_url,
                'key_present': bool(self.key()), 'disabled_reason': self.disabled_reason,
                'circuit_open': self.circuit_open(), 'last_error': self.last_error,
                'session_bound': bool(self.active_session)}

    # ---------- 调用 ----------
    def _headers(self, session_id):
        headers = {'Authorization': 'Bearer ' + self.key(),
                   'Content-Type': 'application/json'}
        if self.app_user_agent:
            headers['User-Agent'] = self.app_user_agent
        if self.session_header and session_id:
            headers[self.session_header] = session_id
        return headers

    def _payload(self, messages, max_tokens, model=None, tools=None, tool_choice=None):
        payload = {'model': model or self.model, 'messages': messages,
                   'max_tokens': max_tokens, 'stream': False}
        # 只有显式传了才带上：不是每个 OpenAI 兼容端点都认 tools，
        # 无条件带会让不支持的工具端点直接 400，连普通回复都发不出去。
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = tool_choice or 'auto'
        if self.temperature is not None:
            payload['temperature'] = self.temperature
        if self.reasoning_effort:
            payload['reasoning_effort'] = self.reasoning_effort
        payload.update(self.extra_body)
        return payload

    def chat(self, messages, max_tokens=1800, model=None, session_id=None):
        """发一次调用；返回 (text, usage dict)。失败抛 ModelUnavailable/ModelAuthError。"""
        text, _tool_calls, usage = self._run(messages, max_tokens, model, session_id)
        return text, usage

    def chat_turn(self, messages, max_tokens=1800, model=None, session_id=None,
                  tools=None, tool_choice=None):
        """一次对话回合：可能只要工具不要正文。返回 (text, tool_calls, usage)。

        工具调用的响应正文是空的（模型把要说的话放进 tool_calls 的 arguments），
        所以不能走 chat()——那条路会把"没有正文"当成失败。
        """
        return self._run(messages, max_tokens, model, session_id, tools, tool_choice)

    def _run(self, messages, max_tokens=1800, model=None, session_id=None,
             tools=None, tool_choice=None):
        if self.disabled_reason:
            raise ModelAuthError('%s 已停用：%s' % (self.name, self.disabled_reason))
        if not self.key():
            raise ModelUnavailable('%s 密钥未配置' % self.name)
        if self.circuit_open():
            raise ModelCircuitOpen('%s 连续失败已熔断 %.0f 秒：%s'
                                   % (self.name, self._open_until - time.time(),
                                      self.last_error or '未知原因'))
        last = None
        for attempt in range(self.max_retries + 1):
            started = time.time()
            try:
                text, tool_calls, usage = self._once(messages, max_tokens, model,
                                                     session_id, tools, tool_choice)
            except ModelAuthError:
                self.disabled_reason = '认证失败(401/403)，需要人工处理'
                self.note_failure('auth')
                raise
            except urllib.error.HTTPError as exc:
                code = getattr(exc, 'code', 0)
                body = ''
                try:
                    body = exc.read(300).decode('utf-8', 'replace')
                except Exception:                       # noqa: BLE001
                    pass
                if code == 429:
                    wait = exc.headers.get('Retry-After') if exc.headers else None
                    try:
                        wait = float(wait)
                    except (TypeError, ValueError):
                        wait = _with_jitter(2.0 * (2 ** attempt))
                    last = ModelUnavailable('429 限流，建议等待 %.0f 秒' % wait)
                    self._record(False, started, error='429', model=model)
                    if attempt < self.max_retries:
                        time.sleep(min(wait, 30.0))
                        continue
                elif code in (401, 403):
                    self.disabled_reason = '认证失败(HTTP %d)，需要人工处理' % code
                    self.note_failure('auth')
                    self._record(False, started, error='auth_%d' % code, model=model)
                    raise ModelAuthError('HTTP %d 认证失败' % code)
                elif 500 <= code < 600:
                    last = ModelUnavailable('HTTP %d' % code)
                    self._record(False, started, error='http_%d' % code, model=model)
                    if attempt < self.max_retries:
                        time.sleep(_with_jitter(1.5 * (2 ** attempt)))
                        continue
                else:
                    last = ModelUnavailable('HTTP %d %s' % (code, body[:120]))
                    self._record(False, started, error='http_%d' % code, model=model)
                    self.note_failure('http_%d' % code)
                    raise last
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = ModelUnavailable('网络/超时: %s' % type(exc).__name__)
                self._record(False, started, error=type(exc).__name__, model=model)
                if attempt < self.max_retries:
                    time.sleep(_with_jitter(1.5 * (2 ** attempt)))
                    continue
            except ValueError as exc:
                # 响应解析失败：不是网络问题，交给调用方按"模型不可用"处理
                self._record(False, started, error='parse', model=model)
                self.note_failure('parse')
                raise ModelUnavailable('响应解析失败: %s' % str(exc)[:80])
            else:
                self.note_success()
                return text, tool_calls, usage
        self.note_failure(type(last).__name__ if last else 'unknown')
        raise last or ModelUnavailable('未知失败')

    def _once(self, messages, max_tokens, model, session_id, tools=None, tool_choice=None):
        url = self.base_url + '/chat/completions'
        payload = self._payload(messages, max_tokens, model, tools, tool_choice)
        headers = self._headers(session_id or self.active_session or self.instance_session())
        req = urllib.request.Request(url, json.dumps(payload, ensure_ascii=False).encode(),
                                     headers=headers)
        started = time.time()
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = resp.read(4 * 1024 * 1024 + 1)
            status = getattr(resp, 'status', 200)
        if len(data) > 4 * 1024 * 1024:
            raise ValueError('模型响应过大')
        try:
            parsed = json.loads(data)
        except ValueError as exc:
            raise ValueError('响应不是JSON: %s' % str(exc)[:60])
        if status in (401, 403):
            raise ModelAuthError('HTTP %d 认证失败' % status)
        choice = (parsed.get('choices') or [{}])[0]
        if choice.get('finish_reason') == 'length':
            raise ValueError('模型输出被长度截断')
        message = choice.get('message') or {}
        tool_calls = message.get('tool_calls')
        if not isinstance(tool_calls, list):
            tool_calls = []
        text = message.get('content')
        if not tool_calls:
            if not isinstance(text, str) or not text.strip():
                raise ValueError('模型无有效正文')
        elif not isinstance(text, str):
            text = ''
        usage = parsed.get('usage') or {}
        self._record(True, started, usage=usage, model=model)
        return text, tool_calls, usage

    def _record(self, ok, started, usage=None, error='', model=None):
        if not self.recorder:
            return
        usage = usage or {}
        try:
            self.recorder({'provider': self.name, 'model': model or self.model,
                           'ok': bool(ok), 'error': error,
                           'latency_ms': int((time.time() - started) * 1000),
                           'prompt_tokens': usage.get('prompt_tokens'),
                           'completion_tokens': usage.get('completion_tokens'),
                           'total_tokens': usage.get('total_tokens')})
        except Exception:                               # noqa: BLE001
            pass


def resolve_providers(cfg, state_dir=None):
    """解析出 {'main': provider, 'ocr': provider or None}；兼容旧的 step_plan 结构。

    state_dir 让调用方（例如 QQ 入口）把凭据/session 落到自己的目录；不传时
    与历史行为完全一致（微信侧），所以现有调用方不受影响。
    """
    cfg = cfg or {}
    new_block = cfg.get('model')
    # enabled=false 表示"已经写好但还没切换"：继续用旧配置，切换是显式的一步
    if isinstance(new_block, dict) and new_block.get('enabled', True):
        main = ModelProvider(new_block, 'main', state_dir=state_dir)
        ocr_block = new_block.get('ocr')
        if isinstance(ocr_block, dict) and ocr_block.get('enabled') is not False:
            if ocr_block.get('mode') == 'disabled' or ocr_block.get('base_url') in ('', None) \
                    and ocr_block.get('mode') == 'disabled':
                ocr = None
            elif ocr_block.get('base_url'):
                ocr = ModelProvider(ocr_block, 'ocr', state_dir=state_dir)
            else:
                ocr = main                      # 同端点同密钥（例如都走 Go）
        else:
            ocr = main
    else:
        legacy = dict(cfg.get('step_plan') or {})
        legacy.setdefault('credential_key', 'step_plan_api_key')
        main = ModelProvider(legacy, 'main', state_dir=state_dir)
        # 旧配置里 OCR 是"同端点、另一个小模型"（step-3.7-flash），且不该带 reasoning_effort
        ocr_model = (cfg.get('step_plan') or {}).get('ocr_model')
        if ocr_model and ocr_model != main.model:
            ocr_block = dict(legacy, model=ocr_model)
            ocr_block.pop('reasoning_effort', None)
            ocr = ModelProvider(ocr_block, 'ocr', state_dir=state_dir)
        else:
            ocr = main
    return {'main': main, 'ocr': ocr}
