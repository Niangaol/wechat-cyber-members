#!/usr/bin/env bash
# 一键跑完独立验证者的全部离线验证（只读仓库，写入只在 verify_qq/ 与 tmpdir）。
# 用法： wsl.exe -d Ubuntu-24.04 -- bash /mnt/d/AgentPrograms/wechat-bot/verify_qq/run_all.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
echo "仓库：$(pwd)"
echo "时间：$(date)"
echo

echo "############ 0. 现有测试基线（被验证对象自带的套件） ############"
python3 -m unittest test_qq_core test_qq_core_policy test_qq_plugin         test_qq_deploy test_qq_shared_state 2>&1 | tail -4
echo

for script in v1_envelope v2_policy v3_media v4_service v5_integration               v7_weak_tests; do
    echo "############ $script ############"
    python3 "verify_qq/$script.py" 2>&1 | tail -12
    echo
done

echo "############ v6_mutation（突变测试，约 15-20 分钟） ############"
echo "需要时手工跑： python3 verify_qq/v6_mutation.py"
echo "报告落在：     verify_qq/mutation-report.txt"
