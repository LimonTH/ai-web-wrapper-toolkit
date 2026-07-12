"""
Adapter for v0.app (Vercel AI).
"""

from src.core.models import ApiEndpoint
from src.proxy.providers.base import BaseProviderAdapter
from src.proxy.providers.registry import register_adapter


@register_adapter
class V0Adapter(BaseProviderAdapter):
    provider_id = "v0"
    provider_name = "V0 by Vercel"
    url_pattern = "v0.app"
    supports = {"chat"}

    def get_endpoint(self, template, block="chat", method="POST") -> ApiEndpoint | None:
        for ep in template.endpoints:
            if "chat" in ep.path.lower() or "completion" in ep.path.lower():
                return ep
        return None

    def build_payload(self, endpoint, body, block="chat") -> dict:
        messages = body.get("messages", [])
        return {
            "messages": messages,
            "model": body.get("model", "v0-default"),
            "stream": body.get("stream", False),
        }

    def extract_content(self, data, block="chat") -> str:
        if isinstance(data, dict):
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return data.get("text", "") or data.get("content", "") or data.get("response", "")
        if isinstance(data, str):
            return data
        return ""

    def extract_stream_chunk(self, chunk, block="chat") -> str | None:
        choices = chunk.get("choices", [])
        if choices:
            delta = choices[0].get("delta", {})
            return delta.get("content")
        return None