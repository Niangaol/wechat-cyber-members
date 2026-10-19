#!/usr/bin/env bash
# 反复跑原始 v4，记录每次结果；一旦出现 FAIL 就保存完整输出并停下。
cd "$(dirname "$0")/.." || exit 1
n=0
fails=0
while [ "$n" -lt 12 ]; do
    n=$((n + 1))
    out=$(python3 verify_qq/v4_service.py 2>&1)
    if printf '%s' "$out" | grep -q '\[FAIL\]'; then
        fails=$((fails + 1))
        printf '%s\n' "$out" > verify_qq/v4-failure-$n.txt
        echo "第 $n 次：FAIL（已存 verify_qq/v4-failure-$n.txt）"
        printf '%s\n' "$out" | grep -E '\[FAIL\]|验证：共'
    else
        echo "第 $n 次：绿"
    fi
done
echo "共 $n 次，失败 $fails 次"
