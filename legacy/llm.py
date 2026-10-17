
"""
LLM 接口层：机器人的"脑"
当前默认 echo（复读机，验证链路用）。后期配模型只需：
  1. config.toml 里 [llm] backend 改成 deepseek / ollama / custom
  2. 对应类已写好，直接能用
加新后端：继承 LLMClient 实现 chat() 一个方法即可
"""
from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod


class LLMClient(ABC):
    """大脑接口：进一段对话，出一段回复"""

    @abstractmethod
    def chat(self, messages: list) -> str:
        """
        messages: [{"role": "user"/"system"/"assistant", "content": "..."}]
        返回：回复文字
        """
        ...


class EchoClient(LLMClient):
    """复读机——链路验证专用，不花一分钱"""

    def chat(self, messages: list) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                return m.get("content", "")
        return ""


class DeepSeekClient(LLMClient):
    """DeepSeek API（年糕主力，便宜）"""

    def __init__(self, api_base: str, api_key: str, model: str = "deepseek-chat",
                 system_prompt: str = ""):
        if not api_key:
            raise ValueError("config.toml 里还没填 api_key")
        self.url = api_base.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt or "你是年糕的微信机器人助手，回复简洁自然，像人话。"

    def chat(self, messages: list) -> str:
        msgs = []
        if self.system_prompt:
            msgs.append({"role": "system", "content": self.system_prompt})
        msgs.extend(messages)
        body = json.dumps({
            "model": self.model,
            "messages": msgs,
            "temperature": 0.7,
            "max_tokens": 500,
        }).encode()
        req = urllib.request.Request(
            self.url, data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"].strip()


class OllamaClient(LLMClient):
    """本地 Ollama（零成本，吃显存，你的 5070 Ti 扛得住）"""

    def __init__(self, base: str = "http://127.0.0.1:11434", model: str = "qwen2.5:7b"):
        self.url = base.rstrip("/") + "/api/chat"
        self.model = model

    def chat(self, messages: list) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            self.url, data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        return data.get("message", {}).get("content", "").strip()


def make_llm(cfg: dict) -> LLMClient:
    """工厂：按 config.toml [llm] 造大脑"""
    llm_cfg = cfg.get("llm", {})
    backend = llm_cfg.get("backend", "echo")
    if backend == "deepseek":
        return DeepSeekClient(
            llm_cfg.get("api_base", "https://api.deepseek.com"),
            llm_cfg.get("api_key", ""),
            llm_cfg.get("model", "deepseek-chat"),
        )
    if backend == "ollama":
        return OllamaClient(llm_cfg.get("ollama_base"), llm_cfg.get("ollama_model"))
    return EchoClient()
