"""QQ 接入核心包：平台无关的同步实现（NoneBot 只做事件解析与发送适配）。

这里集中把 `src/` 加进 sys.path，其它 qq/core 模块直接用裸导入（import memory 等），
避免每个模块各写一遍路径魔法。qq/core 下**不允许** import nonebot（离线测试要能在
没有 nonebot 的系统 python 下跑）。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DEFAULT_STATE_DIR = Path.home() / '.local' / 'state' / 'qq-bot'
