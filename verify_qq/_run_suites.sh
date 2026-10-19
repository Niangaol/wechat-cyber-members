#!/usr/bin/env bash
# 跑指定的验证套件，只打印 FAIL 行与汇总。用法： bash verify_qq/_run_suites.sh v1_envelope v2_policy ...
cd "$(dirname "$0")/.." || exit 1
for s in "$@"; do
    echo "--- $s ---"
    python3 "verify_qq/$s.py" 2>&1 | grep -E "FAIL|OBSERVE|验证：共"
done
