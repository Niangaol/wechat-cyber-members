#!/usr/bin/env bash
# lead 要求：加隔离护栏后连跑 20 次，统计结果。
cd "$(dirname "$0")/.." || exit 1
n=0
pass=0
fail=0
while [ "$n" -lt 20 ]; do
    n=$((n + 1))
    out=$(python3 verify_qq/v4_service.py 2>&1)
    if printf '%s' "$out" | grep -q '\[FAIL\]'; then
        fail=$((fail + 1))
        printf '%s\n' "$out" > "verify_qq/v4-failure-$n.txt"
        echo "第 $n 次：FAIL -> verify_qq/v4-failure-$n.txt"
        printf '%s\n' "$out" | grep -E '\[FAIL\]|隔离被破坏' | head -5
    else
        pass=$((pass + 1))
        if [ "$n" = "1" ]; then
            printf '%s\n' "$out" | grep -A6 '用例隔离审计'
        fi
    fi
done
echo "======================================"
echo "连跑 $n 次：PASS=$pass FAIL=$fail"
