"""WSL 微信协作式 UI 锁：跨进程排他，同线程嵌套可重入；不删除锁文件。"""
import fcntl
import os
import threading
from contextlib import contextmanager
from pathlib import Path

_active = threading.local()


class UILeaseBusy(RuntimeError):
    pass


@contextmanager
def ui_lease(state_dir):
    directory = Path(state_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'wechat-ui.lock'
    key = str(path)
    held = getattr(_active, 'held', None)
    if held is None:
        held = _active.held = {}
    if held.get(key) == os.getpid():
        yield
        return
    # 每线程/进程独立 open 描述符；flock 由内核在崩溃时释放，不靠过期时间。
    with path.open('a+b') as handle:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UILeaseBusy('微信 UI 正被其他协作流程使用，本轮不执行') from exc
        held[key] = os.getpid()
        try:
            yield
        finally:
            held.pop(key, None)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
