#!/usr/bin/env python3
"""QQ 链路的"假 NapCat"端到端自检（lead 编写，2026-10-18）。

为什么需要它：真实 QQ 收发要人工扫码登录，但"事件 → 策略 → 队列 → 模型 → 安全闸 →
发送 API → 台账"这一整条链可以在没有 QQ 账号时先验通。它扮演 NapCat 的角色：
  1) 带 Authorization: Bearer <token> 连上 NoneBot 的反向 WS；
  2) 投一条私聊消息事件；
  3) 等待机器人主动调用 send_msg（OneBot v11 API 调用），收到就回一个成功应答，
     并把模型真正生成的那句话打印出来。

用法（在 WSL 里，需要服务已启动、且 config 里 auto_send=true + 目标号在白名单里）：
    ~/.local/share/qq-bot/venv/bin/python wsl/qq-e2e-fake-napcat.py --user 20002
退出码 0 = 走通（收到并应答了 send_msg）；2 = 超时没等到；3 = 配置/依赖问题。
注意：它会真的调一次模型（消耗 1 单位额度），所以默认只跑一条消息。
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import websockets

ENV_FILE = Path.home() / ".config/qq-bot/qq.env"


def load_token():
    token = ""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("QQ_BOT_ONEBOT_TOKEN="):
                token = line.split("=", 1)[1].strip()
    if not token:
        print("找不到 QQ_BOT_ONEBOT_TOKEN（先跑 wsl/install-qq.sh）", file=sys.stderr)
        raise SystemExit(3)
    return token


async def connect(url, token, self_id):
    headers = {"Authorization": "Bearer " + token, "X-Self-ID": str(self_id),
               "X-Client-Role": "Universal", "User-Agent": "OneBot/11 fake-napcat"}
    # max_size 必须放大：图片消息是 base64 塞在 send_msg 里发过来的（实测一张图 ~4.4MB），
    # websockets 客户端默认只收 1MiB，会把帧判成 1009 message too big 然后断开。
    kwargs = {"max_size": 32 * 1024 * 1024}
    try:
        return await websockets.connect(url, additional_headers=headers, **kwargs)
    except TypeError:                      # 老版本 websockets 用 extra_headers
        return await websockets.connect(url, extra_headers=headers, **kwargs)


async def run(args):
    token = load_token()
    url = args.url
    event = {
        "post_type": "message", "message_type": args.chat_type,
        "sub_type": "friend" if args.chat_type == "private" else "normal",
        "message_id": args.message_id, "user_id": args.user, "self_id": args.self_id,
        "time": int(time.time()),
        "sender": {"user_id": args.user, "nickname": "e2e-probe"},
        "message": ([{"type": "at", "data": {"qq": str(args.self_id)}}] if args.at else [])
                   + ([{"type": "image", "data": {"url": args.image_url, "file": "x.png"}}]
                      if args.image_url else [])
                   + [{"type": "text", "data": {"text": args.text}}],
        "raw_message": args.text,
    }
    if args.chat_type == "group":
        event["group_id"] = args.group
    ws = await connect(url, token, args.self_id)
    async with ws:
        print("CONNECTED", url)
        await ws.send(json.dumps(event, ensure_ascii=False))
        print("SENT_EVENT", json.dumps(event["message"], ensure_ascii=False))
        sent = 0
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(1.0, deadline - time.time()))
            except asyncio.TimeoutError:
                break
            try:
                msg = json.loads(raw)
            except ValueError:
                print("RAW", str(raw)[:120])
                continue
            if isinstance(msg, dict) and msg.get("action"):
                params = json.dumps(msg.get("params", {}), ensure_ascii=False)
                print("API_CALL", msg["action"], params[:600])
                if msg["action"] == "send_msg":
                    await ws.send(json.dumps({"status": "ok", "retcode": 0,
                                              "data": {"message_id": 999001 + sent},
                                              "echo": msg.get("echo")}))
                    sent += 1
                    print("ANSWERED_SEND_MSG_OK", sent)
                    if sent >= args.expect:
                        return 0
                else:
                    # 每个 echo 只能应答一次：同一 echo 回两次会让适配器的
                    # ResultStore 对已完成的 future 再 set_result（InvalidStateError，
                    # 表现为服务端直接断开这条 WS）。
                    await ws.send(json.dumps({"status": "ok", "retcode": 0, "data": {},
                                              "echo": msg.get("echo")}))
            else:
                print("EVENT", str(msg)[:140])
    print("TIMEOUT_NO_SEND_MSG（看 journalctl --user -u qq-bot 里的 qq_* 日志）",
          file=sys.stderr)
    return 2


def main():
    ap = argparse.ArgumentParser(description="假 NapCat：不登录 QQ 也能验通 QQ 链路")
    ap.add_argument("--url", default="ws://127.0.0.1:18080/onebot/v11/ws")
    ap.add_argument("--self-id", default="10001")
    ap.add_argument("--user", default="20002", help="发消息的人（私聊=对方 QQ 号）")
    ap.add_argument("--group", default="888777", help="群号（--chat-type group 时用）")
    ap.add_argument("--chat-type", default="private", choices=("private", "group"))
    ap.add_argument("--text", default="自检：用一句话打个招呼")
    ap.add_argument("--message-id", type=int, default=int(time.time()) % 1000000)
    ap.add_argument("--at", action="store_true", help="群消息里带上真正的 @机器人 段")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--image-url", default="",
                    help="消息里带一张图片（公网 URL，验证收图理解）")
    ap.add_argument("--expect", type=int, default=1,
                    help="等到第几条 send_msg 才收工（生图场景是 2：先文字后图片）")
    raise SystemExit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
