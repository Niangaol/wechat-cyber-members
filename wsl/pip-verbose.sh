#!/bin/bash
python3 -m pip install --break-system-packages nvidia-cuda-runtime-cu12 2>&1 | tail -12
