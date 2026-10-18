"""发送通道抽象（契约 v1 · 第 4 节）。

**只允许发到 event 自己的会话**：接口不接受任意目标参数。这不是洁癖——
一旦"发给谁"能由调用方（或间接由模型输出、被注入的聊天内容）决定，
提示注入就能把机器人变成任意群/任意好友的群发器。

unknown 的语义：请求已经出去了但没拿到确认（超时/断线）。
调用方**绝不允许重发**——重发等于赌"刚才没发出去"，赌错就是双份消息。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SendResult:
    ok: bool
    unknown: bool
    error: str = ''
    message_id: str = ''

    def __post_init__(self):
        # 防御性归一：调用方（NoneBot 侧）直接构造时可能传 None
        self.ok = bool(self.ok)
        self.unknown = bool(self.unknown)
        self.error = str(self.error or '')
        self.message_id = str(self.message_id or '')


class Sender(ABC):
    """一条消息通道：文字、图片、自身账号、在线状态。"""

    @abstractmethod
    def send_text(self, event, text):
        """把 text 发到 event 所在的会话。"""

    @abstractmethod
    def send_image(self, event, path):
        """把本地图片发到 event 所在的会话。"""

    @abstractmethod
    def self_id(self):
        """机器人自己的 QQ 号（用于会话隔离与去重键）。"""

    @abstractmethod
    def online(self):
        """连接是否在线（NoneBot/NapCat 是否握手成功）。"""
