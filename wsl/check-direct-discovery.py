"""好友发现的只读实机验收：独占 UI、不调用模型、不发消息、不写正式登记。"""
import json
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from direct_discovery import DirectDiscovery, list_candidates
from direct_registry import DirectRegistry
from wechat_ui import WeChatUI
from chat_navigator import ChatNavigator
from multimodal import STATE
from ui_lease import ui_lease

cfg = json.loads((ROOT / "config/resident.json").read_text())
ui = WeChatUI(cfg)
with ui_lease(STATE), tempfile.TemporaryDirectory() as directory:
    image = ui.capture()
    print("candidates", list_candidates(ui, image), flush=True)
    discovery = DirectDiscovery(DirectRegistry(Path(directory) / "friends.json"))
    if len(sys.argv)>1 and sys.argv[1] == "--scan":
        cfg["direct_auto_discover"] = True
        print("discovered",discovery.scan(cfg,ui,now=1000),flush=True)
        print("registered",list(discovery.registry.load()),flush=True)
    elif len(sys.argv) > 1:
        name = sys.argv[1]
        original_key = ui.key
        def key_with_evidence(key):
            if key == "Escape":
                from screen import list_x_windows
                print("windows", [(w["id"],w["title"],w["w"],w["h"]) for w in list_x_windows(cfg["display"]) if "wechat" in w["classes"]], flush=True)
                ui.capture().save(ROOT / "shots/discovery-before-close.png")
            return original_key(key)
        ui.key = key_with_evidence
        print("profile", name, discovery.inspect_profile(ui, ChatNavigator(ui), name), flush=True)
        ui.capture().save(ROOT / "shots/discovery-profile-check.png")
        if hasattr(discovery, "last_profile_image"):
            discovery.last_profile_image.save(ROOT / "shots/discovery-contact-page.png")
