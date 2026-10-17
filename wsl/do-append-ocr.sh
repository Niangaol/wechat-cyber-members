#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
python3 - <<'PY'
from pathlib import Path
p = Path("test_ocr_pipeline.py")
lines = p.read_text().splitlines(True)
add = Path("wsl/append-ocr-tests.txt").read_text()
# 去掉末尾的 main 守卫两行，追加新测试后再加回去
while lines and lines[-1].strip() == "":
    lines.pop()
assert lines[-1].strip() == "unittest.main()", repr(lines[-1])
assert lines[-2].strip().startswith("if __name__"), repr(lines[-2])
lines = lines[:-2]
p.write_text("".join(lines) + add)
print("appended, new line count:", len(p.read_text().splitlines()))
PY
tail -24 test_ocr_pipeline.py
python3 -m py_compile test_ocr_pipeline.py && echo COMPILE_OK
