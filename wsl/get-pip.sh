#!/bin/bash
echo "=== 找 pip ==="
ls /usr/bin/pip* /usr/local/bin/pip* 2>/dev/null
python3 -m pip --version 2>&1 | head -2
echo "=== apt 装 python3-pip（快）==="
sudo apt-get install -y -qq python3-pip >/dev/null 2>&1 && echo "apt pip ok"
python3 -m pip --version 2>&1 | head -2
