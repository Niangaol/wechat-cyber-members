"""朋友圈动态采集器：Moments 窗口滚动截图→本地 OCR 提取→inbox 去重入库。
纯本地 0 额度；滚动与窗口操作坐标未标定时安全跳过。"""
import re, time
from wechat_ui import normalize

# Moments 窗口内滚动区域（登录后标定；None=未标定）
SCROLL_REGION = None   # (x1, y1, x2, y2) 窗口相对坐标


def parse_cards(ocr_text):
    """把 Moments 窗口 OCR 文本切成动态卡片。
    heuristic：作者行（短行、含常见昵称特征）后跟内容行；无法可靠切分时
    整屏作为一条（fingerprint 仍按内容去重）。返回 [{author, text}]。"""
    lines = [l.strip() for l in str(ocr_text).splitlines() if l.strip()]
    lines = [l for l in lines if not re.match(r'^(\d+分钟前|\d+小时前|\d+天前|昨天|刚刚)$', l)]
    cards, current = [], None
    for line in lines:
        # 作者行特征：很短（<=15字符）且不像句子（无标点、非纯数字）
        is_author_like = (len(line) <= 15 and not re.search(r'[，。！？、,.!?]', line)
                          and not line.isdigit())
        if is_author_like and (current is None or current['text']):
            current = {'author': line, 'text': ''}
            cards.append(current)
        elif current is not None:
            current['text'] = (current['text'] + ' ' + line)[:300]
        else:
            current = {'author': '', 'text': line[:300]}
            cards.append(current)
    return [c for c in cards if c['text'] or c['author']]


def card_fingerprint(card):
    return normalize(card['author'])[:20] + '|' + normalize(card['text'])[:80]


class MomentsCollector:
    """在 Moments 窗口里滚动采集。坐标未标定只截当前屏（不滚动）。"""

    def __init__(self, ui):
        self.ui = ui

    def collect(self, inbox, screens=2):
        """采集当前屏+下拉一屏。返回新增条数。"""
        added = 0
        seen = set()
        for screen in range(max(1, screens)):
            try:
                image = self.ui.capture()
            except Exception:
                break
            text = self.ui.ocr(image, 6)
            for card in parse_cards(text):
                fp = card_fingerprint(card)
                if fp in seen or fp == '|':
                    continue
                seen.add(fp)
                if inbox.add(card['author'], card['text'], False, fp):
                    added += 1
            if screen + 1 < screens and SCROLL_REGION:
                x1, y1, x2, y2 = SCROLL_REGION
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                self.ui.run(['xdotool', 'mousemove', str(cx), str(cy)])
                self.ui.run(['xdotool', 'click', '5'])
                time.sleep(1.5)
        return added
