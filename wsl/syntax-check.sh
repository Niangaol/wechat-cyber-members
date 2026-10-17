#!/bin/bash
cd /mnt/d/AgentPrograms/wechat-bot
for f in src/*.py; do
  python3 -c "import ast,sys;ast.parse(open(sys.argv[1]).read())" "$f" || { echo "SYNTAX FAIL: $f"; exit 1; }
done
echo "SYNTAX_OK all src files"
