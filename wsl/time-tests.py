"""Run offline unittest discovery with per-test wall timings. No model calls intended."""
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

class TimedResult(unittest.TextTestResult):
    def startTest(self, test):
        self.started = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        elapsed = time.perf_counter() - self.started
        timings.append((elapsed, test.id()))
        super().stopTest(test)

timings = []
blocked = []

def offline_guard(event, args):
    # Audit hooks still catch real calls even if production code swallows the error.
    if event in {'subprocess.Popen', 'os.system', 'socket.connect', 'socket.getaddrinfo'}:
        blocked.append(event)
        raise RuntimeError('Offline tests attempted external I/O: ' + event)

if __name__ == "__main__":
    sys.addaudithook(offline_guard)
    start = time.perf_counter()
    suite = unittest.defaultTestLoader.discover(str(ROOT), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2, resultclass=TimedResult).run(suite)
    print("\nSlowest tests:", flush=True)
    for elapsed, name in sorted(timings, reverse=True)[:15]:
        print(f"{elapsed:8.3f}s  {name}", flush=True)
    print(f"Total including discovery: {time.perf_counter() - start:.3f}s", flush=True)
    print(f"External I/O attempts blocked: {len(blocked)}", flush=True)
    sys.exit(not result.wasSuccessful() or bool(blocked))
