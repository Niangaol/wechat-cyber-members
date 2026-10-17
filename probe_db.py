"""只读探测微信本地数据库 schema（不提取密钥、不注入、不修改）。"""
import os, sqlite3, sys
from pathlib import Path

# 数据目录名是本机登录账号的 wxid，属于个人标识，不写死在仓库里：
#   显式指定：WECHAT_WXID=wxid_xxx python3 probe_db.py
#   不指定时自动取第一个 xwechat_files/wxid_* 目录
WXID = os.environ.get('WECHAT_WXID') or (
    (sorted((Path.home() / 'xwechat_files').glob('wxid_*')) or ['wxid_REPLACE_ME'])[0].name)

BASE = Path.home()/'xwechat_files'/WXID/'db_storage'


def probe(path):
    print('===', path.name, '===')
    try:
        con = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        print('表:', tables[:12])
        for t in tables[:4]:
            try:
                cols = [r[1] for r in con.execute('PRAGMA table_info(%s)' % t)]
                n = con.execute('SELECT count(*) FROM %s' % t).fetchone()[0]
                print('  %s (%d 行): %s' % (t, n, cols[:10]))
                # 尝试取一行看是否明文
                row = con.execute('SELECT * FROM %s LIMIT 1' % t).fetchone()
                if row:
                    sample = str(row[0])[:60]
                    print('    首行样例:', sample)
            except Exception as e:
                print('  读 %s 失败: %s' % (t, type(e).__name__))
        con.close()
    except Exception as e:
        print('打开失败:', type(e).__name__, str(e)[:120])


for name in ['session/session.db', 'general/general.db', 'contact/contact.db']:
    p = BASE/name
    if p.exists():
        probe(p)
