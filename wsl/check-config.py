import json
from pathlib import Path
p = Path("/mnt/d/AgentPrograms/wechat-bot/config/resident.json")
data = json.loads(p.read_text())
print("config ok; keys:", sorted(data.keys())[:12], "...", len(data), "keys")
