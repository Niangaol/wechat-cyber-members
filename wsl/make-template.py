from PIL import Image
im = Image.open('/mnt/d/AgentPrograms/wechat-bot/main-with-chat.png').convert('RGB')
# 「很帅的年糕」列表项：全屏 y~222-248, x~128-340（名字文字区，不含头像/徽章）
crop = im.crop((128, 222, 340, 248))
crop.save('/mnt/d/AgentPrograms/wechat-bot/config/chat-template.png')
print('模板已存:', crop.size)
# 同时 dump 该区域 OCR 看看
