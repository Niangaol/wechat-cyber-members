from PIL import Image
im = Image.open('/mnt/d/AgentPrograms/wechat-bot/main-with-chat.png').convert('RGB')
# 只留名字「很帅...」：避开右侧时间戳（Yesterday 22:07）
crop = im.crop((128, 162, 290, 194))
crop.save('/mnt/d/AgentPrograms/wechat-bot/config/chat-template.png')
print('窄模板:', crop.size)
