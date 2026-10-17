"""
数据模型：消息、任务、动作
全机器人系统通用的"语言"，所有模块之间只传这些结构
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MessageType(str, Enum):
    """消息/任务类型——覆盖年糕要的全部功能"""
    TEXT = "text"            # 纯文字
    IMAGE = "image"          # 图片（本地路径）
    LINK = "link"            # 网页链接（作为文字发送，微信自动出卡片）
    EMOJI = "emoji"          # 表情包（微信表情面板里的）
    PAT = "pat"              # 拍一拍（双击聊天记录里的头像）
    AT = "at"                # @某人（输入框敲 @ 再选人）
    FILE = "file"            # 文件


@dataclass
class WeChatMessage:
    """从微信界面监测到的一条消息"""
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    chat_name: str = ""            # 会话名（左侧列表显示的名字）
    sender: str = ""               # 发送者（群聊里是昵称，私聊等同 chat_name）
    content: str = ""              # 文字内容（图片/表情为空）
    msg_type: MessageType = MessageType.TEXT
    image_path: Optional[str] = None
    is_group: bool = False         # 是否群聊
    at_me: bool = False            # 群里是否 @ 了我
    seen_at: float = field(default_factory=time.time)

    def __str__(self) -> str:
        who = self.sender if self.is_group else self.chat_name
        return f"[{self.msg_type.value}] {who}: {self.content or '(非文字)'}"


@dataclass
class BotTask:
    """机器人要执行的一个动作（发给执行层的指令）"""
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_type: MessageType = MessageType.TEXT
    chat_name: str = ""            # 目标会话
    text: str = ""                 # TEXT/LINK/AT 的文字内容
    image_path: str = ""           # IMAGE/FILE 的本地路径
    emoji_name: str = ""           # EMOJI：表情名或最近表情序号
    pat_target: str = ""           # PAT：拍谁
    at_target: str = ""            # AT：@谁
    delay_before: float = 0.5      # 执行前等待（秒），模拟人的节奏
    created_at: float = field(default_factory=time.time)
    finished: bool = False
    error: str = ""


@dataclass
class MomentTask:
    """发朋友圈任务"""
    text: str = ""
    image_paths: list = field(default_factory=list)
    mention: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


class Action(str, Enum):
    """执行层动作原语（执行器必须实现的接口）"""
    CLICK = "click"          # 点击 (x, y)
    DOUBLE_CLICK = "double"  # 双击 (x, y)——拍一拍用
    RIGHT_CLICK = "right"    # 右键 (x, y)
    TYPE = "type"            # 输入文字
    HOTKEY = "hotkey"        # 组合键，如 ctrl+v / return
    SCROLL = "scroll"        # 滚动 (x, y, direction)
    DRAG = "drag"            # 拖拽 (x1,y1)->(x2,y2)——发图片用
