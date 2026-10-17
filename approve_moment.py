"""确认并发布朋友圈草稿（手动触发）。用法：
  python3 approve_moment.py list      # 看待确认草稿
  python3 approve_moment.py send 1    # 发布 id=1 的草稿（需坐标已标定）"""
import json, sqlite3, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent/'src'))
from wechat_ui import WeChatUI, SafetyError
from moments_publisher import MomentsPublisher, PublisherError

ROOT = Path(__file__).parent
CFG = json.loads((ROOT/'config'/'resident.json').read_text())
COORDS_FILE = ROOT/'config'/'moments-coords.json'


def db():
    return sqlite3.connect(str(Path.home()/'.local'/'state'/'wechat-bot'/'ledger.sqlite'))


def load_coords():
    if COORDS_FILE.exists():
        return json.loads(COORDS_FILE.read_text())
    return {}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'list'
    conn = db()
    if cmd == 'list':
        rows = conn.execute("SELECT id,topic,text,image,state FROM moments WHERE state IN ('DRAFT','APPROVED') ORDER BY id DESC").fetchall()
        if not rows:
            print('没有待确认的草稿'); return
        for mid, topic, text, image, state in rows:
            print('#%d [%s] (%s)' % (mid, state, topic))
            print('  文案:', text)
            print('  配图:', image or '(无)')
        return
    if cmd == 'send':
        if len(sys.argv) < 3:
            print('用法: approve_moment.py send <id>'); return
        mid = int(sys.argv[2])
        row = conn.execute('SELECT text,image FROM moments WHERE id=?', (mid,)).fetchone()
        if not row:
            print('草稿不存在'); return
        text, image = row
        conn.execute('UPDATE moments SET state=? WHERE id=?', ('APPROVED', mid)); conn.commit()
        coords = load_coords()
        if not coords:
            print('坐标未标定：先跑 calibrate 生成 config/moments-coords.json')
            print('（草稿已标记 APPROVED，标定后重跑本命令即可发布）')
            return
        ui = WeChatUI(CFG)
        pub = MomentsPublisher(ui, coords)
        try:
            pub.publish(text, image or None)
        except (PublisherError, SafetyError, NotImplementedError) as e:
            print('发布中止:', type(e).__name__, str(e)[:120])
            conn.execute('UPDATE moments SET state=? WHERE id=?', ('DRAFT', mid)); conn.commit()
            print('（草稿已退回 DRAFT，可修正后重试）')
            return
        conn.execute('UPDATE moments SET state=?,published=? WHERE id=?',
                     ('PUBLISHED', time.time(), mid)); conn.commit()
        print('已发布 #%d' % mid)
        return
    print('未知命令:', cmd)


if __name__ == '__main__':
    main()
