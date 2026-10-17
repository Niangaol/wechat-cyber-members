#!/bin/bash
set -e
IMG_SRC=/home/niangao/.local/state/wechat-bot/media/gen-1792077117.png
DST_DIR=/home/niangao/xwechat_files
ls -d $DST_DIR || { echo "xwechat_files 不存在"; exit 1; }
cp "$IMG_SRC" $DST_DIR/moment-test.png
ls -la $DST_DIR/moment-test.png
python3 -c "
from PIL import Image
im = Image.open('$DST_DIR/moment-test.png')
print('size', im.size, 'mode', im.mode)
"
