"""自动发现私聊的持久登记：只接受 UI 好友资料核验结果，不以群名猜类型。"""
import json
import os
from pathlib import Path
from wechat_ui import normalize


def admitted_name(cfg, name):
    key = normalize(name)
    if not key or len(name) > 128 or any(c in name for c in ("\n", "\r", "…")):
        return False
    denied = list(cfg.get("direct_blacklist", [])) + list(cfg.get("group_whitelist", []))
    if key in {normalize(x) for x in denied}:
        return False
    types = {normalize(k): v for k, v in cfg.get("chat_types", {}).items()}
    return types.get(key, "direct") == "direct"


class DirectRegistry:
    """名单独立落盘，避免发现流程覆盖人工配置；失效/损坏时不放行。"""
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict) or data.get("version") != 1:
            return {}
        rows = data.get("friends", {})
        if not isinstance(rows, dict):
            return {}
        return {name: row for name, row in rows.items()
                if isinstance(name, str) and isinstance(row, dict)
                and row.get("proof") == "contact_profile"
                and isinstance(row.get("wechat_id"), str) and row["wechat_id"].strip()}

    def register(self, cfg, name, wechat_id, proof):
        if not cfg.get("direct_enabled", True) or not admitted_name(cfg, name):
            return False
        if proof != "contact_profile" or not isinstance(wechat_id, str) or not wechat_id.strip():
            return False
        rows = self.load()
        # 重名的不同账号禁止自动覆盖，避免发错人。
        same = next((v for k, v in rows.items() if normalize(k) == normalize(name)), None)
        if same and same["wechat_id"] != wechat_id:
            return False
        rows[name] = {"wechat_id": wechat_id, "proof": proof,
                      "pending_initial": same.get("pending_initial", False) if same else True}
        self._save(rows)
        return True

    def _save(self, rows):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps({"version": 1, "friends": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temp, 0o600)
        temp.replace(self.path)

    def pending_initial(self, cfg, name):
        return (cfg.get("direct_enabled", True) and admitted_name(cfg,name)
                and bool(self.load().get(name, {}).get("pending_initial")))

    def ack_initial(self, name):
        rows = self.load()
        if name in rows and rows[name].get("pending_initial"):
            rows[name]["pending_initial"] = False
            self._save(rows)

    def apply(self, cfg):
        """每轮从原配置合并，黑名单/禁用开关立即生效，绝不扩展群白名单。"""
        result = dict(cfg)
        if not cfg.get("direct_enabled", True):
            return result
        names = list(cfg.get("direct_whitelist", []))
        types = dict(cfg.get("chat_types", {}))
        for name in self.load():
            if not admitted_name(cfg, name):
                continue
            if normalize(name) not in {normalize(n) for n in names}:
                names.append(name)
            types[name] = "direct"
        result["direct_whitelist"] = names
        result["chat_types"] = types
        return result
