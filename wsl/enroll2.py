from PIL import Image
im = Image.open('/mnt/d/AgentPrograms/wechat-bot/main-with-chat.png').convert('RGB')
crop = im.crop((283, 20, 700, 61))
crop.save('/mnt/d/AgentPrograms/wechat-bot/config/target-title.png')
print('标题模板已更新:', crop.size)
