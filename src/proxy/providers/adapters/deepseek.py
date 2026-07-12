from typing import Any

from src.core.models import ApiEndpoint, WebsiteTemplate
from src.proxy.providers.base import BaseProviderAdapter
from src.proxy.providers.registry import register_adapter

"""
Adapter for DeepSeek (deepseek.com).
DeepSeek API is OpenAI-compatible.
"""


@register_adapter
class DeepSeekAdapter(BaseProviderAdapter):
    provider_id = "deepseek"
    provider_name = "DeepSeek"
    url_pattern = "deepseek.com"
    supports = {"chat"}

    def get_endpoint(
            self,
            template: WebsiteTemplate,
            block: str = "chat",
            method: str = "POST",
    ) -> ApiEndpoint | None:
        for ep in template.endpoints:
            if "chat/completions" in ep.path or "completion" in ep.path.lower():
                return ep
        return None

    def build_payload(
            self,
            endpoint: ApiEndpoint,
            body: dict[str, Any],
            block: str = "chat",
    ) -> dict[str, Any]:
        return {
            "messages": body.get("messages", []),
            "model": body.get("model", "deepseek-chat"),
            "stream": body.get("stream", False),
            "temperature": body.get("temperature", 0.7),
            "max_tokens": body.get("max_tokens", 4096),
            "top_p": body.get("top_p", 1.0),
        }

    def extract_content(
            self,
            data: dict[str, Any] | str | list,
            block: str = "chat",
    ) -> str:
        if isinstance(data, dict):
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return data.get("text", "") or data.get("content", "")
        if isinstance(data, str):
            return data
        if isinstance(data, list):
            return str(data)
        return ""

    def extract_stream_chunk(
            self,
            chunk_data: dict[str, Any],
            block: str = "chat",
    ) -> str | None:
        choices = chunk_data.get("choices", [])
        if choices:
            delta = choices[0].get("delta", {})
            return delta.get("content")
        return None
