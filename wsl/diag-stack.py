# 打出被拦截 Popen 的完整调用栈。
import sys
import traceback
import unittest
from pathlib import Path

ROOT = Path("/mnt/d/AgentPrograms/wechat-bot")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

stacks = []

def guard(event, args):
    if event == "subprocess.Popen":
        stacks.append("".join(traceback.format_stack()[:-1]) + "\nCMD: " + str(args[0]))
        raise RuntimeError("blocked")

class Quiet(unittest.TextTestResult):
    def addError(self, test, err):
        if stacks:
            print("STACK for", test.id())
            print(stacks[-1])
        unittest.TextTestResult.addError(self, test, err)
    def addFailure(self, test, err):
        if stacks:
            print("STACK (at failure) for", test.id())
            print(stacks[-1])
        unittest.TextTestResult.addFailure(self, test, err)

sys.addaudithook(guard)
loader = unittest.TestLoader()
suite = loader.loadTestsFromName("test_send_binding.BindingTests.test_group_only_config_without_default_direct")
result = unittest.TextTestRunner(verbosity=2, resultclass=Quiet).run(suite)
if not stacks:
    print("no Popen attempted; failures:", len(result.failures), "errors:", len(result.errors))
    for t, b in result.failures + result.errors:
        print(b)
