"""模型调用账单：token 消耗、按小时分布、折算金额。

用法：
    python3 wsl/bill.py              今天 + 最近 7 天
    python3 wsl/bill.py --days 30    改统计区间

数据来源：运行状态 ledger.sqlite 的 model_calls 表（每次模型调用落一行，
含 prompt/completion/total tokens）。只统计模型调用；生图走的是另一个 API
（千问 qwen-image），不在这张表里，要看图的钱得另外算。

单价说明：PRICE 是 OpenRouter 上 step-3.7-flash 的公开参考价。机器人实际打的是
StepFun 官方端点（api.stepfun.com），价格可能不同，以账号真实账单为准；
拿到准确单价后改 PRICE 即可（单位：美元 / 百万 tokens）。
"""
import argparse, datetime, os, shutil, sqlite3, sys, tempfile, time

STATE = os.path.expanduser("~/.local/state/wechat-bot")
LEDGER = os.path.join(STATE, "ledger.sqlite")
PRICE = {"in": 0.20, "out": 1.15}
RATE = 7.2


def money(pin, pout):
    return (pin or 0) / 1e6 * PRICE["in"] + (pout or 0) / 1e6 * PRICE["out"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    if not os.path.exists(LEDGER):
        print("找不到账本：" + LEDGER)
        return 1
    tmp = os.path.join(tempfile.gettempdir(), "ledger_bill.sqlite")
    shutil.copy(LEDGER, tmp)
    db = sqlite3.connect(tmp)
    today = datetime.date.today().strftime("%Y-%m-%d")
    now = time.time()
    day_sql = "date(created, 'unixepoch', 'localtime')"

    row = db.execute("SELECT count(*), sum(ok), sum(prompt_tokens), "
                    "sum(completion_tokens), sum(total_tokens) "
                    "FROM model_calls WHERE " + day_sql + " = ?",
                    (today,)).fetchone()
    n, ok, pin, pout, tot = [x or 0 for x in row]
    replies = db.execute("SELECT count(*) FROM turns WHERE role='assistant' "
                         "AND " + day_sql + " = ?", (today,)).fetchone()[0] or 0

    print("=" * 68)
    print("今日 %s     单价参考：输入 $%.2f/M，输出 $%.2f/M"
          % (today, PRICE["in"], PRICE["out"]))
    print("=" * 68)
    print("  模型调用        : %d 次（成功 %d / 失败 %d）" % (n, ok, n - ok))
    print("  真正发出的回复  : %d 条  ->  每条摊 %.1f 次调用、%s tokens"
          % (replies, n / max(1, replies), format(int(tot / max(1, replies)), ",")))
    print("  输入 tokens     : %14s" % format(pin, ","))
    print("  输出 tokens     : %14s" % format(pout, ","))
    print("  合计            : %14s" % format(tot, ","))
    usd = money(pin, pout)
    print("  折算            : %14s   （约 %.2f 元）" % ("$%.4f" % usd, usd * RATE))
    if n - ok:
        hidden = (n - ok) * (tot / max(1, ok))
        print("  注意            : 失败 %d 次没记到 token；若 provider 照样计费，约再多 %s tokens（+$%.4f）"
              % (n - ok, format(int(hidden), ","), money(hidden, 0)))

    print("")
    print("  按小时（localtime）")
    print("    时段    调用     tokens      金额    失败")
    for h, c, t, f in db.execute("SELECT strftime('%H', created, "
                                  "'unixepoch', 'localtime') h, count(*), "
                                  "sum(total_tokens), "
                                  "sum(CASE WHEN ok=0 THEN 1 ELSE 0 END) "
                                  "FROM model_calls WHERE " + day_sql +
                                  "=? GROUP BY h ORDER BY h", (today,)):
        print("    %s:00  %5d  %10s  $%7.4f  %4d"
              % (h, c, format(t or 0, ","), money(t or 0, 0) * 0.88, f or 0))

    print("")
    print("  最近 %d 天" % args.days)
    print("    日期          调用   回复    合计tokens       金额")
    since = now - args.days * 86400
    replies_day = {}
    for d, c in db.execute("SELECT " + day_sql + ", count(*) FROM turns "
                           "WHERE role='assistant' AND created > ? "
                           "GROUP BY 1", (since,)):
        replies_day[d] = c
    for d, c, t, pi, po in db.execute("SELECT " + day_sql + " d, count(*), "
                                      "sum(total_tokens), sum(prompt_tokens), "
                                      "sum(completion_tokens) FROM model_calls "
                                      "WHERE created > ? GROUP BY d "
                                      "ORDER BY d DESC LIMIT ?",
                                      (since, args.days)):
        print("    %s  %5d  %4d  %12s  $%8.4f"
              % (d, c, replies_day.get(d, 0), format(t or 0, ","), money(pi, po)))

    print("")
    print("  失败原因分布（累计）")
    for err, c in db.execute("SELECT error, count(*) FROM model_calls "
                           "WHERE ok=0 GROUP BY error ORDER BY 2 DESC"):
        print("    %-26s %d 次" % (err or "(空)", c))
    print("")
    print("  生图走千问 qwen-image（另一个 API），不在这张表里。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
