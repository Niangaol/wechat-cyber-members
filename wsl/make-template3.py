from PIL import Image
im = Image.open('/mnt/d/AgentPrograms/wechat-bot/main-with-chat.png').convert('RGB')
# 「很帅的年糕」列表项名字行：y 160-200（其下 220-280 是 Yesterday/Link 第二行）
crop = im.crop((128, 160, 340, 198))
crop.save('/mnt/d/AgentPrograms/wechat-bot/config/chat-template.png')
print('模板:', crop.size)
