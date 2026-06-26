"""
Model Layer - Call large model APIs
Supports selecting different models, currently only supports Qwen (OpenAI-compatible format)
"""

import os
from typing import Optional, List, Dict, Any
from openai import OpenAI

# ========== Configuration Constants ==========
# Please fill in your Qwen API Key here
QWEN_API_KEY = "sk-1185d2957e454b7b945cb6baeb606b4a"
QWEN_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# ===========================================


class ModelClient:
    """Model client supporting multiple large model APIs"""

    SUPPORTED_MODELS = {
        "qwen": ["qwen-turbo", "qwen-plus", "qwen-max"],
    }

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """
        Initialize model client

        Args:
            api_key: API key, defaults to QWEN_API_KEY constant or environment variable
            base_url: API base URL, defaults to QWEN_API_BASE constant or environment variable
        """
        self.api_key = api_key or QWEN_API_KEY if QWEN_API_KEY != "your_qwen_api_key_here" else os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or (QWEN_API_BASE if QWEN_API_BASE != "https://dashscope.aliyuncs.com/compatible-mode/v1" else os.getenv("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
        self.client = None
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def set_model(self, model_name: str) -> bool:
        """
        Set the currently used model

        Args:
            model_name: Model name, e.g. "qwen-turbo", "qwen-plus"

        Returns:
            bool: Whether the setting was successful
        """
        for model_type, models in self.SUPPORTED_MODELS.items():
            if model_name in models:
                self.current_model = model_name
                return True
        return False

    def get_available_models(self) -> Dict[str, List[str]]:
        """Get all available models"""
        return self.SUPPORTED_MODELS.copy()

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        发送对话请求

        Args:
            messages: 消息列表，格式为[{"role": "user", "content": "..."}]
            model: 模型名称，默认使用当前设置的模型
            temperature: 温度参数
            max_tokens: 最大token数
            **kwargs: 其他参数

        Returns:
            Dict: 包含响应内容的字典
        """
        if not self.client:
            raise ValueError("API key not set. Please set OPENAI_API_KEY environment variable or pass api_key.")

        target_model = model or getattr(self, 'current_model', 'qwen-turbo')

        response = self.client.chat.completions.create(
            model=target_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

        return {
            "model": target_model,
            "content": response.choices[0].message.content,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }
        }

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs
    ):
        """
        Streaming chat request

        Args:
            messages: Message list
            model: Model name
            temperature: Temperature parameter
            **kwargs: Other parameters

        Yields:
            str: Incremental output content fragments
        """
        if not self.client:
            raise ValueError("API key not set. Please set OPENAI_API_KEY environment variable or pass api_key.")

        target_model = model or getattr(self, 'current_model', 'qwen-turbo')

        stream = self.client.chat.completions.create(
            model=target_model,
            messages=messages,
            temperature=temperature,
            stream=True,
            **kwargs
        )

        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


# Global model client instance
_model_client: Optional[ModelClient] = None


def get_model_client() -> ModelClient:
    """Get the global model client instance"""
    global _model_client
    if _model_client is None:
        _model_client = ModelClient()
    return _model_client


def init_model_client(api_key: str = None, base_url: str = None) -> ModelClient:
    """Initialize the global model client"""
    global _model_client
    _model_client = ModelClient(api_key=api_key, base_url=base_url)
    return _model_client
