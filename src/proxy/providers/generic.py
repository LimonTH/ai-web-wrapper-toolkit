from typing import Any

from src.proxy.providers.base import BaseProviderAdapter

"""
Generic provider adapter — fallback when no YAML config or adapter exists.
Minimal implementation; phased out in favor of YAML-driven configs.
"""


class GenericAdapter(BaseProviderAdapter):
    """Universal adapter suitable for any website (fallback)."""

    provider_id = "generic"
    provider_name = "Generic Provider"
    supports = {"chat", "image_gen", "files", "tools", "tts", "stt"}

    def build_payload(
        self,
        endpoint_key: str,
        body: dict[str, Any],
        block: str = "chat",
    ) -> dict[str, Any]:
        messages = body.get("messages", [])
        return {
            "messages": messages,
            "model": body.get("model", "default"),
            "stream": body.get("stream", False),
        }

    def extract_content(
        self,
        data: dict[str, Any] | str | list,
        block: str = "chat",
    ) -> str:
        if isinstance(data, str):
            return data
        if isinstance(data, list):
            return str(data[0]) if data else ""
        if isinstance(data, dict):
            # OpenAI-compatible response
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return (
                data.get("text", "")
                or data.get("content", "")
                or data.get("response", "")
            )
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
        return chunk_data.get("content") or chunk_data.get("text")
