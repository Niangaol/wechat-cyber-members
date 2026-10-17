#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
python3 - <<'PY'
import json
c = json.load(open('config/resident.json'))
print('JSON_OK friends =', c['interact']['friends'])
PY
MSYS_NO_PATHCONV=1 wsl -d Ubuntu-24.04 -- python3 -m unittest test_moment_interact test_integration 2>&1 | tail -4
