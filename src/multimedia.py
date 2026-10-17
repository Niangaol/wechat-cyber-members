# 多模态媒体文件管理：气泡截图按会话隔离存放。
from pathlib import Path
import hashlib

STATE = Path.home()/'.local'/'state'/'wechat-bot'


def inbox_media_dir(chat_key):
    # 该会话的气泡截图目录（chat_key 做目录名，隔离）
    safe = hashlib.sha256(str(chat_key).encode('utf-8')).hexdigest()
    d = STATE/'media'/'inbox'/safe
    d.mkdir(parents=True, exist_ok=True)
    return d
