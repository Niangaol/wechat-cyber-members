"""按模块定位离线守卫拦截的外部 I/O 来源。"""
import sys
import unittest
from pathlib import Path

ROOT = Path("/mnt/d/AgentPrograms/wechat-bot")
sys.path.insert(0, str(ROOT))

blocked = []

def guard(event, args):
    if event in {"subprocess.Popen", "os.system", "socket.connect", "socket.getaddrinfo"}:
        blocked.append(event)
        raise RuntimeError("offline: " + event)

loader = unittest.TestLoader()
for path in sorted(ROOT.glob("test_*.py")):
    blocked.clear()
    sys.addaudithook(guard)
    suite = loader.loadTestsFromName(path.stem)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    ok = result.wasSuccessful() and not blocked
    print(f"{path.stem:28s} ok={ok} blocked={len(blocked)} fail={len(result.failures)} err={len(result.errors)}")
    if blocked:
        print("   events:", blocked[:6])
