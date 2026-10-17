# 诊断 test_send_binding：记录每次被拦截的 subprocess 命令与所属测试。
import sys
import unittest
from pathlib import Path

ROOT = Path("/mnt/d/AgentPrograms/wechat-bot")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

current = {"test": "?", "events": []}

def guard(event, args):
    if event == "subprocess.Popen":
        cmd = args[0] if args else None
        current["events"].append((current["test"], str(cmd)[:80]))
        raise RuntimeError("offline Popen: " + str(cmd))

class Named(unittest.TextTestResult):
    def startTest(self, test):
        current["test"] = test.id()
        unittest.TextTestResult.startTest(self, test)

sys.addaudithook(guard)
loader = unittest.TestLoader()
suite = loader.loadTestsFromName("test_send_binding")
result = unittest.TextTestRunner(verbosity=2, resultclass=Named).run(suite)
print("=== blocked Popen attempts ===")
for test, cmd in current["events"]:
    print(test, "->", cmd)
print("failures:", len(result.failures), "errors:", len(result.errors))
