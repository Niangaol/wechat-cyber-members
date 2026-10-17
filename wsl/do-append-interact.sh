#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
python3 - <<'PY'
from pathlib import Path
p = Path("test_moment_interact.py")
text = p.read_text()
add = Path("wsl/append-interact-tests.txt").read_text()
marker = "if __name__ == '__main__':\n    unittest.main(verbosity=2)\n"
assert text.endswith(marker), repr(text[-60:])
p.write_text(text[:-len(marker)] + add)
print("appended")
PY
python3 -m unittest test_moment_interact -v 2>&1 | tail -14
