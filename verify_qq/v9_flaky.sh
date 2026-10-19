#!/usr/bin/env bash
# 反复单跑同一个用例，量化它是否 flaky。只读仓库。
cd "$(dirname "$0")/.." || exit 1
N=25
pass=0
fail=0
fails_detail=""
for i in $(seq 1 "$N"); do
    out=$(python3 -m unittest test_qq_core.StatusTests.test_status_has_contract_fields_and_is_written_atomically 2>&1)
    if printf '%s' "$out" | grep -q '^OK'; then
        pass=$((pass + 1))
    else
        fail=$((fail + 1))
        if [ -z "$fails_detail" ]; then
            fails_detail=$(printf '%s' "$out" | grep -m1 -A3 'AssertionError' | head -4)
        fi
    fi
done
echo "单跑 $N 次：PASS=$pass FAIL=$fail"
echo "首次失败详情："
echo "$fails_detail"
