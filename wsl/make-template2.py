from PIL import Image
im = Image.open('/mnt/d/AgentPrograms/wechat-bot/main-with-chat.png').convert('RGB')
# 会话打开后「很帅的年糕」置顶在列表第一项：y 80-140，名字在 y~92-120, x 128-340
crop = im.crop((128, 92, 340, 120))
crop.save('/mnt/d/AgentPrograms/wechat-bot/config/chat-template.png')
print('新模板:', crop.size)
# 顺带存一个第二备用：File Transfer 下方的原始位置版本不存在了，只信这一个
