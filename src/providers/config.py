"""
ProviderConfig — loads YAML, builds body by rules, parses response via JSONPath.

YAML is the single source of truth for provider API configuration.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from src.core.config import settings


class ProviderConfig:
    """
    Loads YAML from data/providers/{provider_id}.yaml and provides:
    - build_body(endpoint_key, openai_body) → dict
    - extract_content(endpoint_key, response_data) → str
    - extract_stream_chunk(endpoint_key, chunk_data) → str | None
    """

    def __init__(self, provider_id: str, data: dict[str, Any]) -> None:
        self.provider_id = provider_id
        self._data = data
        self._endpoints: dict[str, Any] = data.get("endpoints", {})

    @property
    def name(self) -> str:
        return self._data.get("name", self.provider_id)

    @property
    def base_url(self) -> str:
        return self._data.get("base_url", "")

    @property
    def supports(self) -> set[str]:
        return set(self._endpoints.keys())

    def get_endpoint(self, endpoint_key: str) -> dict[str, Any] | None:
        """Get endpoint config by key (e.g. 'chat', 'chat_init')."""
        return self._endpoints.get(endpoint_key)

    # ── Body building ──────────────────────────────────────────────

    def build_body(
        self, endpoint_key: str, openai_body: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Build request payload for the given endpoint from OpenAI body.

        Syntax in YAML body values:
        - ${body.field}    → openai_body.get("field")
        - ${messages}      → shorthand for ${body.messages}
        - /${project_id}   → static string with placeholder (kept as-is)
        - Everything else  → static value
        """
        ep = self.get_endpoint(endpoint_key)
        if not ep:
            return {}
        body_template = ep.get("body", {})
        return self._resolve_value(body_template, openai_body)

    def _resolve_value(self, template: Any, openai_body: dict[str, Any]) -> Any:
        if isinstance(template, dict):
            return {
                k: self._resolve_value(v, openai_body)
                for k, v in template.items()
            }
        if isinstance(template, list):
            return [self._resolve_value(item, openai_body) for item in template]
        if isinstance(template, str):
            m = re.match(r"^\$\{(.+)\}$", template)
            if m:
                expr = m.group(1).strip()
                if expr.startswith("body."):
                    return openai_body.get(expr[5:])
                return openai_body.get(expr)
            return template
        return template

    # ── Content extraction ─────────────────────────────────────────

    def extract_content(self, endpoint_key: str, data: Any) -> str:
        """
        Extract text from response data using JSONPath fallback rules.

        YAML syntax:
          content:
            - "$.choices[0].message.content"
            - "$.text"

        Array of paths = fallbacks; first non-null, non-empty value wins.
        """
        ep = self.get_endpoint(endpoint_key)
        if not ep:
            return ""

        extract = ep.get("extract", {})
        paths = extract.get("content", [])
        if isinstance(paths, str):
            paths = [paths]

        for path in paths:
            result = self._jsonpath_get(data, path)
            if result is not None:
                if isinstance(result, str) and result.strip():
                    return result
                if not isinstance(result, str):
                    return str(result)
        return ""

    def extract_stream_chunk(
        self, endpoint_key: str, chunk_data: Any
    ) -> str | None:
        """Extract text from a single SSE streaming chunk via JSONPath."""
        ep = self.get_endpoint(endpoint_key)
        if not ep:
            return None

        extract = ep.get("extract", {})
        path = extract.get("stream")
        if not path:
            return None

        result = self._jsonpath_get(chunk_data, path)
        if isinstance(result, str):
            return result
        return None

    # ── Headers ────────────────────────────────────────────────────

    def get_headers(
        self, endpoint_key: str, stream: bool = False
    ) -> dict[str, str]:
        """Get headers for the given endpoint, merged with safe defaults."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": (
                "text/event-stream" if stream else "application/json"
            ),
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            ),
        }
        ep = self.get_endpoint(endpoint_key)
        if ep:
            ep_headers = ep.get("headers", {})
            headers.update(ep_headers)
        return headers

    # ── URL / method helpers ───────────────────────────────────────

    def get_endpoint_url(self, endpoint_key: str) -> str | None:
        ep = self.get_endpoint(endpoint_key)
        if not ep:
            return None
        path = ep.get("path", "")
        return f"{self.base_url.rstrip('/')}{path}"

    def get_endpoint_method(self, endpoint_key: str) -> str:
        ep = self.get_endpoint(endpoint_key)
        if not ep:
            return "POST"
        return ep.get("method", "POST")

    # ── JSONPath resolver ──────────────────────────────────────────

    @staticmethod
    def _jsonpath_get(data: Any, path: str) -> Any:
        """
        Minimal JSONPath resolver.

        "$.key"           → data["key"]
        "$.key.subkey"    → data["key"]["subkey"]
        "$.arr[0].key"    → data["arr"][0]["key"]
        """
        if not path.startswith("$."):
            return None

        remaining = path[2:]
        if not remaining:
            return data

        current = data
        # Split by "." while keeping array indices attached: "arr[0]"
        parts = re.findall(r"[^.]+(?:\[[^\]]*\])?", remaining)

        for part in parts:
            if current is None:
                return None

            bracket = re.match(r"(.+)\[(\d+)\]$", part)
            if bracket:
                key = bracket.group(1)
                idx = int(bracket.group(2))
                if isinstance(current, dict):
                    current = current.get(key)
                if isinstance(current, (list, tuple)) and idx < len(current):
                    current = current[idx]
                else:
                    return None
            else:
                if isinstance(current, dict):
                    current = current.get(part)
                else:
                    return None

        return current


# ─── Load helpers ─────────────────────────────────────────────


def load_provider_config(provider_id: str) -> ProviderConfig | None:
    """Load a single provider config from data/providers/{id}.yaml."""
    path = (
        Path(settings.project_root)
        / "data" / "providers" / f"{provider_id}.yaml"
    )
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data or not isinstance(data, dict):
            return None
        return ProviderConfig(provider_id=provider_id, data=data)
    except Exception:
        return None


def load_all_provider_configs() -> dict[str, ProviderConfig]:
    """Load all provider configs from data/providers/*.yaml."""
    providers_dir = Path(settings.project_root) / "data" / "providers"
    if not providers_dir.exists():
        return {}

    configs: dict[str, ProviderConfig] = {}
    for yaml_path in sorted(providers_dir.glob("*.yaml")):
        try:
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data or not isinstance(data, dict):
                continue
            pid = data.get("provider_id", yaml_path.stem)
            configs[pid] = ProviderConfig(provider_id=pid, data=data)
        except Exception:
            continue

    return configs
