#!/usr/bin/env bash
# 反复跑带探针的 v4 调试副本，直到复现失败，并打印失败点前后的 DECIDE 记录。
cd "$(dirname "$0")/.." || exit 1
python3 verify_qq/_make_v4_debug.py || exit 1
n=0
while [ "$n" -lt 8 ]; do
    n=$((n + 1))
    out=$(python3 verify_qq/_v4_debug.py 2>&1)
    if printf '%s' "$out" | grep -q '\[FAIL\]'; then
        echo "第 $n 次跑挂了；下面是失败行与它前面的 DECIDE 记录："
        printf '%s\n' "$out" | grep -E 'DECIDE|FAIL|验证：共' | tail -40
        exit 0
    fi
    echo "第 $n 次绿"
done
echo "8 次都没复现"
