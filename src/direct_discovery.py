"""纯 UI 新好友发现：本地 OCR 列表 → 完整标题 → 好友资料的微信号。

聊天内容永远不能作为会话类型证明；不调用模型、不发送任何消息。
"""
import logging
import re
import time
from wechat_ui import normalize, SafetyError, title_matches
from chat_navigator import ChatNavigator
from direct_registry import admitted_name


def contact_id(text, expected):
    """只解析资料卡而非聊天区；必须同时存在昵称、微信号及好友操作。"""
    compact = normalize(text)
    if not normalize(expected) or normalize(expected) not in compact:
        return None
    if any(label in compact.lower() for label in ("groupname", "groupnotice", "群公告", "群名称")):
        return None
    if not any(label in compact.lower() for label in ("sendmessage", "发消息", "remark", "备注")):
        return None
    match = re.search(r"(?:WeChat\s*ID|Weixin\s*ID|微信号)\s*[:：]?\s*([A-Za-z][A-Za-z0-9_\-]{5,63})", text, re.I)
    return match.group(1) if match else None


def chinese_line(ui, image):
    import io
    import numpy as np
    from PIL import Image
    a = np.asarray(image.convert("RGB")).copy()
    a[(a.max(2).astype("int16")-a.min(2).astype("int16")) > 50] = 255
    crop = Image.fromarray(a).convert("L")
    out = io.BytesIO()
    crop.resize((crop.width*2,crop.height*2)).point(lambda p:0 if p<150 else 255).save(out,"PNG")
    return ui.run(["tesseract","stdin","stdout","-l","chi_sim","--psm","7"],
                  out.getvalue(),timeout=20).decode("utf-8").strip()


def candidate_rows(ui, image):
    """用头像纵向占位定位名称行，避免把消息预览读作好友昵称。"""
    import numpy as np
    a = np.asarray(image.convert("RGB"), dtype="int16")
    strip = a[65:image.height-12, 78:110]
    # 列表底色白/浅灰；头像有明显暗色或彩色像素。
    marked = (((strip.max(2)-strip.min(2)) > 30) | (strip.mean(2) < 180)).sum(1) >= 8
    ys = np.flatnonzero(marked)
    runs = []
    for y in ys:
        if runs and y-runs[-1][-1] <= 5:
            runs[-1].append(int(y))
        else:
            runs.append([int(y)])
    result = []
    for run in runs:
        if not 20 <= run[-1]-run[0] <= 52:
            continue
        top = 65+run[0]
        crop = image.crop((121, max(60, top-5), 294, top+20))
        name = ui.ocr(crop,7).strip()
        if not re.search(r"[\u4e00-\u9fff]", name):
            alternate = chinese_line(ui,crop)
            if len(re.findall(r"[\u4e00-\u9fff]", alternate)) >= 2:
                name = alternate
        if name and "…" not in name and "..." not in name:
            result.append((name,(170,top+15)))
    return result


def list_candidates(ui,image):
    return list(dict.fromkeys(name for name,_ in candidate_rows(ui,image)))


def finally_restore(ui):
    """发现流程结束（正常或异常）都把左侧导航切回聊天页。

    实测教训：中断在通讯录页时，会话列表不在视野里，常驻机器人每个会话都切不进去，
    一轮 observe 卡到 70+ 秒。恢复失败不抛，交给主循环的 recover_ui 兜底。
    """
    try:
        if hasattr(ui, 'open_chat_tab'):
            ui.open_chat_tab()
    except Exception:      # noqa: BLE001
        pass


class DirectDiscovery:
    def __init__(self, registry):
        self.registry = registry
        self.last_scan = 0
        self.attempted = {}

    def inspect_profile(self, ui, nav, name):
        return self.inspect_contact(ui, name)

    def inspect_contact(self, ui, name):
        """通讯录中的好友详情是正向类型证据，聊天文字不能伪造该页面。"""
        from chat_navigator import ocr_tsv, merge_list_lines
        ui.capture()
        ax, ay = getattr(ui, "last_abs", (0, 0))
        def click(x, y):
            ui.run(["xdotool", "mousemove", str(ax+x), str(ay+y)])
            ui.run(["xdotool", "click", "1"])
            time.sleep(0.4)
        click(32, 151)
        try:
            image = ui.capture()
            # 通讯录选中图标呈绿色，聊天页的图标为灰色。
            def selected_contacts(frame):
                area = frame.crop((20,140,45,163)).convert("RGB")
                return sum(g>110 and g-r>45 and g-b>20 for r,g,b in area.getdata()) >= 8
            if not selected_contacts(image):
                return None
            contact_nav = ChatNavigator(ui)
            image = contact_nav.scroll_list_top()
            hits = []
            for page in range(4):
                self.last_profile_image = image.copy()
                words = ocr_tsv(ui,image.crop((138,60,333,image.height-10)))
                for cy,text,_ in merge_list_lines(words):
                    if not title_matches(name,text,False):
                        text = chinese_line(ui,image.crop((138,max(60,60+int(cy)-15),333,min(image.height,60+int(cy)+15))))
                    if title_matches(name,text,False):
                        hits.append((cy,text))
                if hits:
                    break
                image = contact_nav.scroll_list_page()
                if not selected_contacts(image):
                    return None
            if len(hits) != 1:
                return None
            click(170, 60+int(hits[0][0]))
            image = ui.capture()
            if not selected_contacts(image):
                return None
            self.last_profile_image = image.copy()
            header = image.crop((566,67,840,95))
            names = [chinese_line(ui,header), ui.ocr(header,7)]
            if not any(title_matches(name,t,False) for t in names):
                return None
            fields = ui.ocr(image.crop((340,95,image.width-10,image.height-30)),6)
            return contact_id(name+"\n"+fields, name)
        finally:
            click(32,100)


    def scan(self, cfg, ui, now=None):
        now = time.monotonic() if now is None else now
        if not cfg.get("direct_enabled", True) or not cfg.get("direct_auto_discover", False):
            return []
        if now-self.last_scan < max(10, float(cfg.get("direct_discovery_seconds", 60))):
            return []
        self.last_scan = now
        nav = ChatNavigator(ui)
        image = ui.capture()
        # 活跃/新收到消息的会话自动浮到顶部，不必全量轮询通讯录。
        image = nav.scroll_list_top()
        known = {normalize(n) for n in self.registry.apply(cfg).get("direct_whitelist", [])}
        known.update(normalize(n) for n in cfg.get("group_whitelist", []))
        added = []
        inspected = 0
        for name in list_candidates(ui, image):
            key = normalize(name)
            if (any(title_matches(n,name,False) for n in known)
                    or key.lower() in {"filetransfer", "weixinteam", "wechatteam"}
                    or not admitted_name(cfg,name)):
                continue
            if now-self.attempted.get(key, -1000000) < 300:
                continue
            self.attempted[key] = now
            inspected += 1
            try:
                uid = self.inspect_profile(ui, nav, name)
                if uid and self.registry.register(cfg, name, uid, "contact_profile"):
                    logging.info("direct_discovered chat=%s", name)
                    added.append(name)
            except SafetyError as exc:
                logging.info("direct_discovery_skipped chat=%s reason=%s", name, str(exc)[:80])
            if inspected >= 3:
                break
        finally_restore(ui)
        return added
