import json
from typing import Any

from src.core.models import WebsiteTemplate, ApiEndpoint
from src.proxy.providers.base import BaseProviderAdapter

"""
Generic provider adapter — universal adapter (fallback).
Used by default when no specific adapter is found.
"""


class GenericAdapter(BaseProviderAdapter):
    """Universal adapter suitable for any website."""

    provider_id = "generic"
    provider_name = "Generic Provider"
    supports = {"chat", "image_gen", "files", "tools", "tts", "stt"}

    _MAX_CONTENT_CHARS = 200_000

    def get_endpoint(
            self,
            template: WebsiteTemplate,
            block: str = "chat",
            method: str = "POST",
    ) -> ApiEndpoint | None:
        """Scoring-based endpoint selection."""
        candidates = list(template.endpoints)
        if not candidates:
            return None

        scored = [
            (self._score_endpoint(ep, block, method), ep)
            for ep in candidates
        ]
        scored.sort(key=lambda x: x[0], reverse=True)

        best_score, best_ep = scored[0]
        if best_score >= 50:
            return best_ep

        for ep in candidates:
            if ep.functional_block == block:
                return ep

        return candidates[0]

    def _score_endpoint(
            self, ep: ApiEndpoint, target_block: str, preferred_method: str = "POST"
    ) -> int:
        if ep.functional_block != target_block:
            return -1
        score = 0
        if ep.method == preferred_method:
            score += 50
        elif ep.method == "GET":
            score += 10
        if ep.is_streaming:
            score += 30
        if ep.body_template:
            body_str = json.dumps(ep.body_template).lower()
            chat_keys = ["message", "messages", "content", "prompt", "conversation", "input"]
            if any(k in body_str for k in chat_keys):
                score += 15
        order_bonus = max(0, 10 - (ep.order or 0))
        score += order_bonus
        return score

    def build_payload(
            self,
            endpoint: ApiEndpoint,
            body: dict[str, Any],
            block: str = "chat",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if endpoint.body_template:
            payload = json.loads(json.dumps(endpoint.body_template))

        if block == "chat":
            messages = body.get("messages", [])
            last_message = messages[-1]["content"] if messages else ""
            self._deep_set(payload, "message", {"content": last_message})
            self._deep_set(payload, "messages", messages)

        elif block == "image_gen":
            prompt = body.get("messages", [{}])[-1].get("content", "")
            payload["prompt"] = prompt
            payload["n"] = body.get("n", 1)
            payload["size"] = body.get("size", "1024x1024")

        elif block == "tts":
            messages = body.get("messages", [])
            last_msg = messages[-1].get("content", "") if messages else ""
            payload["text"] = last_msg
            payload["voice"] = body.get("voice", "alloy")

        elif block == "stt":
            payload["audio"] = body.get("audio", "")

        return payload

    def extract_content(
            self,
            data: dict[str, Any] | str | list,
            block: str = "chat",
    ) -> str:
        result = self._extract_recursive(data, block, depth=0)
        if result and len(result) > self._MAX_CONTENT_CHARS:
            return result[:self._MAX_CONTENT_CHARS] + "\n\n[response truncated]"
        return result or ""

    def _extract_recursive(
            self, data: Any, block: str = "chat", depth: int = 0
    ) -> str | None:
        if depth > 3:
            return None

        if isinstance(data, str):
            return data
        if isinstance(data, list):
            return self._extract_recursive(data[0], block, depth + 1) if data else None
        if not isinstance(data, dict):
            return None

        candidates = []

        if block == "chat":
            candidates = [
                data.get("message", {}).get("content"),
                data.get("choices", [{}])[0].get("message", {}).get("content"),
                data.get("choices", [{}])[0].get("text"),
                data.get("response"),
                data.get("text"),
                data.get("content"),
                data.get("reply"),
                data.get("answer"),
                data.get("output"),
            ]
        elif block == "image_gen":
            candidates = [
                data.get("data", [{}])[0].get("url") if isinstance(data.get("data"), list) else None,
                data.get("data", [{}])[0].get("b64_json") if isinstance(data.get("data"), list) else None,
                data.get("url"),
                data.get("image"),
            ]
        elif block == "tts":
            candidates = [
                data.get("audio"),
                data.get("url"),
            ]

        for c in candidates:
            if c and isinstance(c, str) and len(c) >= 1:
                return c

        for v in list(data.values())[:10]:
            if isinstance(v, (dict, list, str)):
                result = self._extract_recursive(v, block, depth + 1)
                if result:
                    return result
        return None

    def extract_stream_chunk(
            self,
            chunk_data: dict[str, Any],
            block: str = "chat",
    ) -> str | None:
        if block == "chat":
            choices = chunk_data.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content")
                if content:
                    return content
            content = chunk_data.get("content") or chunk_data.get("text")
            if content and isinstance(content, str):
                return content
        return None

    def _deep_set(self, d: dict[str, Any], key: str, value: Any) -> None:
        parts = key.split(".", 1)
        if len(parts) == 1:
            d[key] = value
        else:
            if parts[0] not in d:
                d[parts[0]] = {}
            if isinstance(d[parts[0]], dict):
                self._deep_set(d[parts[0]], parts[1], value)
