from PIL import Image
im = Image.open('/mnt/d/AgentPrograms/wechat-bot/live-list.png').convert('RGB')
# live-list：第一项 Agent聊天测试群(4)、第二 File Transfer、第三 很帅的年糕(y~222-250)
crop = im.crop((128, 222, 290, 250))
crop.save('/mnt/d/AgentPrograms/wechat-bot/config/chat-template.png')
print('模板(很帅的年糕名字行):', crop.size)
