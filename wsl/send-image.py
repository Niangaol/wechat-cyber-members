"""独立发图命令入口；不导入或操作常驻 Resident。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))
from image_send_tool import main

if __name__ == '__main__':
    raise SystemExit(main())
