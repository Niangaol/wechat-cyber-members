#!/bin/bash
# 打开「很帅的年糕」会话并重新登记标题模板
export DISPLAY=:99
WID=$(xwininfo -root -tree 2>/dev/null | grep '"Weixin"' | grep -oE '0x[0-9a-f]+' | head -1)
echo "主窗口: $WID"
xwininfo -id "$WID" > /tmp/w.txt 2>/dev/null
WX=$(grep "Absolute upper-left X" /tmp/w.txt | sed 's/[^0-9]//g')
WY=$(grep "Absolute upper-left Y" /tmp/w.txt | sed 's/[^0-9]//g')
echo "窗口位置: $WX,$WY"

# 会话项「很帅的年糕」：边栏右列表，File Transfer 下方，相对约 (200,150)
xdotool mousemove $((WX + 200)) $((WY + 150))
sleep 0.3
xdotool click 1
sleep 2

import -window "$WID" /mnt/d/AgentPrograms/wechat-bot/main-with-chat.png && echo SHOT_OK

python3 -c "
from PIL import Image
im = Image.open('/mnt/d/AgentPrograms/wechat-bot/main-with-chat.png').convert('RGB')
im.crop((283, 20, 700, 61)).save('/d/AgentPrograms/wechat-bot/config/target-title.png')
print('标题模板已更新')
"
