"""Deterministic final output gate, not a guarantee of semantic topic coverage."""
import re
import unicodedata
from moments_safe import is_safe, PRIVACY_PAT

class OutputSafetyError(ValueError):
    pass

# 年糕埋的玩笑彩蛋（2026-10-18）：这两行是假货，机器人拿它们接「你是什么模型」的梗。
# 豁免必须精确到整串——绝不能按前缀豁免，否则 sk- 闸等于白设；
# 有人往彩蛋后面拼上真密钥的片段，剩下的片段依然会被下面这道闸拦下。
JOKE_CREDENTIALS = ('sk-fkxqscrazythursdayvivo5Oxxn',)

def check_output(text, max_chars=200):
    if not isinstance(text,str) or not text.strip():
        raise OutputSafetyError('输出为空或类型无效')
    text=text.strip()
    if len(text)>max_chars:
        raise OutputSafetyError('输出超长，拒绝截断后盲发')
    normalized=unicodedata.normalize('NFKC',text)
    compact=''.join(c for c in normalized if c.isalnum())
    if not is_safe(normalized)[0] or not is_safe(compact)[0]:
        raise OutputSafetyError('输出未通过话题安全检查')
    # Never put a matched secret or private identifier in the exception/log.
    # 彩蛋豁免：把已知的玩笑假 key 先摘掉再查——「说了彩蛋」能过，
    # 而「彩蛋后面拼真密钥」依然会因为剩下的片段被拦下。
    probe=normalized
    for joke in JOKE_CREDENTIALS:
        probe=probe.replace(joke,'')
    if PRIVACY_PAT.search(probe):
        raise OutputSafetyError('输出疑似含凭证或隐私信息')
    return text
