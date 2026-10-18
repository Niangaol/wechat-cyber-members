"""Windows 上跑 resident 相关测试用的 fcntl 桩（Linux 才有的模块）。
仅供本地测试：PYTHONPATH 指向本目录。不要放到 src/ 里，也不要在 Linux 上用。"""
LOCK_EX = 2
LOCK_NB = 4
LOCK_SH = 1
LOCK_UN = 8

def flock(fd, operation):
    return None

def lockf(fd, cmd, len=0, start=0, whence=0):
    return None
