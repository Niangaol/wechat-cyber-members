"""配置装载与校验（契约 §9 冻结 schema）。

分工：qq/bot.py 负责 NoneBot 监听侧（host/port/path/token 的最终生效值），
这里负责把 qq.json 变成一份**可信、字段齐全**的配置字典。契约 §9 末尾点名的五条：

1. token 生效顺序：os.environ[onebot.token_env] 优先，其次 onebot.token；
   两者都空 → resolve_token 抛 QQConfigError（fail-closed：绝不无鉴权开监听）。
2. groups 必须是 dict（键是数字字符串），空 dict 合法（= 谁都不接）。
3. direct_policy 只接受 blacklist/whitelist，其它值当 blacklist 并 warn。
4. state_dir 走 Path(...).expanduser()，创建时 chmod 700。
5. 未知字段忽略并 warn，不因为多写一个键就崩。
   下划线开头的键是**注释**（qq.example.json 里几十条都是），静默跳过不 warn。

这里只做"读与校验"：不碰数据库、不发网络请求，也不打印任何密钥明文。
"""
import copy
import json
import logging
import os
from pathlib import Path

DEFAULT_TOKEN_ENV = 'QQ_BOT_ONEBOT_TOKEN'
DEFAULT_STATE_DIR = '~/.local/state/qq-bot'
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 18080
DEFAULT_PATH = '/onebot/v11/ws'

VALID_DIRECT_POLICIES = ('blacklist', 'whitelist')
VALID_PLAIN_MODES = ('at_only', 'selective', 'idle', 'all')

# 契约 §9 冻结 schema 的顶层字段
SCHEMA_KEYS = frozenset((
    'self_id', 'state_dir', 'auto_send', 'onebot', 'napcat', 'direct_policy',
    'direct_blacklist', 'direct_whitelist', 'group_policy', 'groups',
    'mention_aliases', 'limits', 'min_reply_seconds', 'max_replies_per_hour',
    'max_pending', 'task_ttl_seconds', 'reply_max_chars', 'reply_image_limit',
    'image_generation', 'media', 'model', 'web_search', 'hot_feed',
))
# qq-core 自己支持的补充项（不在 §9 表里，但属于已知字段，不该被当成"未知键"warn）
CORE_KEYS = frozenset((
    'max_queue', 'event_max_age_s', 'poll_interval_s', 'status_interval_s',
    'claim_lease_s', 'image_prompt_prefix', 'media_max_bytes',
    'media_timeout_s', 'max_images_per_event',
    'links',      # 契约 §7.1 的链接阅读（结构与微信 resident.json 的 links 段一致）
))
KNOWN_KEYS = SCHEMA_KEYS | CORE_KEYS

# 数值字段的默认值（缺失就补上；类型不对就用默认值并 warn）
NUMERIC_DEFAULTS = {
    'min_reply_seconds': 3,
    'max_replies_per_hour': 30,
    'max_pending': 200,
    'task_ttl_seconds': 600,
    'reply_max_chars': 200,
    'reply_image_limit': 2,
}
MEDIA_DEFAULTS = {'max_bytes': 10 * 1024 * 1024, 'timeout_s': 15,
                  'max_images': 2, 'keep_days': 14}
IMAGE_DEFAULTS = {'enabled': False, 'max_per_hour': 3, 'credentials_file': ''}
# 链接阅读（契约 §7.1）：这一段会**原样**喂给 src/web_reader.fetch_public_text(url, cfg['links'])
LINKS_DEFAULTS = {'enabled': True, 'max_urls': 2, 'max_bytes': 250000,
                  'max_chars': 9000, 'timeout': 10, 'total_budget_seconds': 12}
LIMITS_DEFAULTS = {'window_5h': 100, 'window_1d': 500}


class QQConfigError(ValueError):
    """配置不合格。fail-closed：宁可拒绝启动，也不要带着错配置跑起来。"""


def _sink(warn):
    """warn 回调：默认走 logging，测试可以传一个列表 append 进来收。"""
    if warn is None:
        return logging.warning
    return warn


def _num(block, key, default, warn, where):
    """取数字：缺失用默认；类型不对 warn 后用默认（不崩）。"""
    value = block.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        warn('%s.%s 应该是数字，实际是 %s，改用默认值 %r'
             % (where, key, type(value).__name__, default))
        return default
    return value


def _bool(block, key, default, warn, where):
    value = block.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        warn('%s.%s 应该是 true/false，实际是 %s，改用默认值 %r'
             % (where, key, type(value).__name__, default))
        return default
    return value


def normalize(cfg, *, env=None, warn=None, warn_unknown=True):
    """归一 + 校验，返回**新的**配置字典（不改调用方传进来的那份）。

    缺的字段补默认值，坏的字段 warn 后用默认值/最保守取值：
    配置读得懂一半也好过整个服务起不来，但"读不懂的那些"必须留下痕迹。
    """
    warn = _sink(warn)
    if not isinstance(cfg, dict):
        raise QQConfigError('配置顶层必须是 JSON 对象，实际是 %s' % type(cfg).__name__)
    out = copy.deepcopy(cfg)

    # §9.5 未知字段忽略并 warn（下划线开头是注释，静默跳过）
    if warn_unknown:
        for key in out:
            if str(key).startswith('_') or key in KNOWN_KEYS:
                continue
            warn('未知配置字段 %r 已忽略（契约 §9.5：多写一个键不该让程序崩）' % (key,))

    # §9.4 state_dir：expanduser，创建时 chmod 700（建目录的动作在 prepare_state_dir）
    raw_dir = out.get('state_dir')
    if raw_dir is None or (isinstance(raw_dir, str) and not raw_dir.strip()):
        raw_dir = DEFAULT_STATE_DIR
    if not isinstance(raw_dir, str):
        warn('state_dir 应该是字符串，实际是 %s，改用默认值 %s'
             % (type(raw_dir).__name__, DEFAULT_STATE_DIR))
        raw_dir = DEFAULT_STATE_DIR
    out['state_dir'] = str(Path(raw_dir).expanduser())

    out['auto_send'] = _bool(out, 'auto_send', False, warn, '顶层')
    out['self_id'] = _text_id(out.get('self_id'))

    # §9.2 groups 必须是 dict（键是数字字符串），空 dict 合法
    groups = out.get('groups')
    if groups is None:
        groups = {}
    if not isinstance(groups, dict):
        raise QQConfigError('groups 必须是对象（键 = 群号字符串），实际是 %s'
                            % type(groups).__name__)
    clean_groups = {}
    for key, value in groups.items():
        if str(key).startswith('_'):
            continue
        group_id = str(key).strip()
        if not group_id.isdigit():
            warn('groups 的键 %r 不是数字群号，已忽略（fail-closed：不接这个群）' % (key,))
            continue
        if not isinstance(value, dict):
            warn('groups[%s] 必须是对象，实际是 %s，已忽略'
                 % (group_id, type(value).__name__))
            continue
        mode = value.get('plain_mode')
        if mode is not None:
            # 契约 §10：plain_mode 先 strip().lower() 再判合法性（"ALL" 合法）。
            # 这里把定稿写回去，别让 config 说一套、policy 做另一套：
            # 以前大写会 warn 说"按 at_only 处理"，而 policy 自己 lower() 后当 all 用。
            normalized = str(mode).strip().lower()
            if normalized in VALID_PLAIN_MODES:
                value = dict(value)
                value['plain_mode'] = normalized
                mode = normalized
            else:
                warn('groups[%s].plain_mode=%r 不是 %s 之一，按最保守的 at_only 处理'
                     % (group_id, mode, '/'.join(VALID_PLAIN_MODES)))
        clean_groups[group_id] = value
    out['groups'] = clean_groups

    # §9.3 direct_policy 只接受 blacklist/whitelist，其它值当 blacklist
    policy = out.get('direct_policy')
    if not isinstance(policy, str) or policy.strip().lower() not in VALID_DIRECT_POLICIES:
        if policy is not None:
            warn('direct_policy=%r 不是 blacklist/whitelist，按 blacklist 处理（fail-closed）'
                 % (policy,))
        policy = 'blacklist'
    out['direct_policy'] = policy.strip().lower()
    for key in ('direct_blacklist', 'direct_whitelist'):
        value = out.get(key)
        if value is None:
            out[key] = []
        elif not isinstance(value, list):
            warn('%s 应该是数组，实际是 %s，按空名单处理' % (key, type(value).__name__))
            out[key] = []
    if out.get('group_policy') not in (None, 'whitelist'):
        warn('group_policy=%r 不支持：QQ 侧固定 whitelist（未登记的群一律不接）'
             % (out.get('group_policy'),))
    out['group_policy'] = 'whitelist'

    # 早期别名：max_queue → 契约 §9 的 max_pending（只在没写 max_pending 时折算）
    if out.get('max_pending') is None and out.get('max_queue') is not None:
        out['max_pending'] = out['max_queue']
    for key, default in NUMERIC_DEFAULTS.items():
        out[key] = _num(out, key, default, warn, '顶层')
    for key, default in LIMITS_DEFAULTS.items():
        block = out.get('limits')
        if not isinstance(block, dict):
            if block is not None:
                warn('limits 应该是对象，实际是 %s，改用默认值' % type(block).__name__)
            block = {}
        out['limits'] = dict(block)
        out['limits'][key] = _num(block, key, default, warn, 'limits')

    for name, defaults in (('media', MEDIA_DEFAULTS),
                           ('image_generation', IMAGE_DEFAULTS),
                           ('links', LINKS_DEFAULTS)):
        block = out.get(name)
        if not isinstance(block, dict):
            if block is not None:
                warn('%s 应该是对象，实际是 %s，改用默认值' % (name, type(block).__name__))
            block = {}
        merged = dict(defaults)
        for key, default in defaults.items():
            if isinstance(default, bool):
                merged[key] = _bool(block, key, default, warn, name)
            elif isinstance(default, (int, float)):
                merged[key] = _num(block, key, default, warn, name)
            else:
                value = block.get(key)
                merged[key] = str(value) if isinstance(value, str) else default
        out[name] = merged

    # hot_feed：契约 §10 裁定默认 **false**（整段缺失、或写了但没写 enabled）。
    # 理由是热榜要走网络：手写的最小配置和 qq.example.json 都不该悄悄出网，
    # 要开的人自己写 enabled=true。
    hot = out.get('hot_feed')
    if hot is None:
        out['hot_feed'] = {'enabled': False, 'refresh_seconds': 300}
    else:
        if not isinstance(hot, dict):
            warn('hot_feed 应该是对象，实际是 %s，按关闭处理' % type(hot).__name__)
            hot = {}
        out['hot_feed'] = {
            'enabled': _bool(hot, 'enabled', False, warn, 'hot_feed'),
            'refresh_seconds': _num(hot, 'refresh_seconds', 300, warn, 'hot_feed')}

    onebot = out.get('onebot')
    if not isinstance(onebot, dict):
        if onebot is not None:
            warn('onebot 应该是对象，实际是 %s，改用默认值' % type(onebot).__name__)
        onebot = {}
    out['onebot'] = {
        'host': str(onebot.get('host') or DEFAULT_HOST),
        'port': int(_num(onebot, 'port', DEFAULT_PORT, warn, 'onebot')),
        'path': str(onebot.get('path') or DEFAULT_PATH),
        'token': str(onebot.get('token') or ''),
        'token_env': str(onebot.get('token_env') or DEFAULT_TOKEN_ENV) or DEFAULT_TOKEN_ENV,
    }
    return out


def resolve_token(cfg, env=None):
    """契约 §9.1：环境变量优先，其次配置文件；两者都空 → 抛异常。

    返回的是**明文 token**，调用方负责别把它写进日志或状态文件。
    """
    block = cfg.get('onebot') if isinstance(cfg, dict) else None
    block = block if isinstance(block, dict) else {}
    name = str(block.get('token_env') or DEFAULT_TOKEN_ENV).strip() or DEFAULT_TOKEN_ENV
    environ = os.environ if env is None else env
    value = str(environ.get(name) or '').strip()
    if value:
        return value
    value = str(block.get('token') or '').strip()
    if value:
        return value
    raise QQConfigError(
        '没有可用的 access token：环境变量 %s 与 onebot.token 都是空的。\n'
        '两端必须一致：先 export %s=<随机串>（或填进 qq.json 的 onebot.token），'
        '再把同一个 token 填进 NapCat 的反向 ws 配置。' % (name, name))


def effective_state_dir(cfg):
    """state_dir 的最终路径（expanduser，不建目录）。"""
    raw = (cfg or {}).get('state_dir') or DEFAULT_STATE_DIR
    return Path(str(raw)).expanduser()


def prepare_state_dir(cfg):
    """契约 §9.4：建目录并 chmod 700，返回展开后的路径。

    db / media / STOP / status.json 都在这一个目录里，权限必须是 700：
    里面会落聊天内容与凭据路径，别的用户不该看得见。
    """
    path = effective_state_dir(cfg)
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError as exc:                      # 权限改不动不该让服务起不来
        logging.warning('qq_state_dir_chmod_failed path=%s type=%s',
                        path, type(exc).__name__)
    return path


def load_config(path, *, env=None, require_token=False, prepare_dir=False, warn=None):
    """读 qq.json → 归一 → 校验。

    文件不存在 / 不是合法 JSON / 顶层不是对象 → QQConfigError（启动即失败，别猜）。
    require_token=True 时顺带执行 §9.1 的 token 闸（默认关：token 由启动路径显式调
    resolve_token 检查，避免调用方还没加载 env 文件就被误判成"没有 token"）。
    """
    target = Path(str(path)).expanduser()
    if not target.is_file():
        raise QQConfigError('找不到配置文件：%s\n先复制示例：'
                            'cp qq/config/qq.example.json qq/config/qq.json' % target)
    try:
        data = json.loads(target.read_text(encoding='utf-8'))
    except Exception as exc:                    # noqa: BLE001 外部文件什么都可能是
        raise QQConfigError('配置文件不是合法 JSON：%s（%s）' % (target, exc))
    cfg = normalize(data, env=env, warn=warn)
    if require_token:
        resolve_token(cfg, env)
    if prepare_dir:
        prepare_state_dir(cfg)
    return cfg


def resolve_self_id(cfg):
    """绑定账号：先看 cfg['self_id']，再看 state_dir/self_id.txt（登录后写回的那份）。"""
    given = _text_id((cfg or {}).get('self_id'))
    if given:
        return given
    return read_self_id(effective_state_dir(cfg))


def read_self_id(state_dir):
    """读 state_dir/self_id.txt；没有或坏掉返回空串。"""
    try:
        return _text_id((Path(state_dir) / 'self_id.txt').read_text(encoding='utf-8'))
    except OSError:
        return ''


def write_self_id(state_dir, self_id):
    """把绑定到的 QQ 号写回 state_dir/self_id.txt（权限 600）。"""
    value = _text_id(self_id)
    if not value:
        return None
    path = Path(state_dir) / 'self_id.txt'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + '\n', encoding='utf-8')
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _text_id(value):
    """QQ 号统一成字符串：JSON 里可能写成数字。"""
    if value is None or isinstance(value, bool):
        return ''
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else str(value)
    return str(value).strip()
