"""Deterministic final output gate, not a guarantee of semantic topic coverage."""
import re
import unicodedata
from moments_safe import is_safe, PRIVACY_PAT

class OutputSafetyError(ValueError):
    pass

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
    if PRIVACY_PAT.search(normalized):
        raise OutputSafetyError('输出疑似含凭证或隐私信息')
    return text
