from typing import Any

from src.providers.config import ProviderConfig

"""
Base provider adapter — plugin interface for site-specific API adapters.
Now config-driven: default methods delegate to ProviderConfig.
Adapters can override any method for custom logic.
"""


class BaseProviderAdapter:
    """
    Base provider adapter class.

    Attributes:
    - provider_id: str
    - provider_name: str
    - url_pattern: str  — URL substring for auto-mapping
    - supports: set[str] — which endpoint keys are supported
    - config: ProviderConfig | None — loaded from YAML
    """

    provider_id: str = ""
    provider_name: str = ""
    url_pattern: str = ""
    supports: set[str] = {"chat"}
    config: ProviderConfig | None = None

    # ── Config-driven defaults ─────────────────────────────────────

    def build_payload(
        self,
        endpoint_key: str,
        body: dict[str, Any],
        block: str = "chat",
    ) -> dict[str, Any]:
        """Default: delegates to ProviderConfig.build_body()."""
        if self.config:
            return self.config.build_body(endpoint_key, body)
        return body

    def extract_content(
        self,
        data: dict[str, Any] | str | list,
        block: str = "chat",
    ) -> str:
        """Default: delegates to ProviderConfig.extract_content()."""
        if self.config:
            return self.config.extract_content(block, data)
        if isinstance(data, str):
            return data
        return ""

    def extract_stream_chunk(
        self,
        chunk_data: dict[str, Any],
        block: str = "chat",
    ) -> str | None:
        """Default: delegates to ProviderConfig.extract_stream_chunk()."""
        if self.config:
            return self.config.extract_stream_chunk(block, chunk_data)
        return None

    # ── Legacy method kept for backward compat (unused in new flow) ─

    def get_headers(
        self,
        endpoint_key: str,
        stream: bool = False,
        block: str = "chat",
    ) -> dict[str, str]:
        """Get headers — from config if available, else defaults."""
        if self.config:
            return self.config.get_headers(endpoint_key, stream=stream)
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            ),
        }
        return headers

    # ── Model helpers (used by transformer) ─────────────────────────

    def get_model_id(self, provider_id: str) -> str:
        return provider_id.lower().replace(" ", "-").replace("_", "-")

    def get_model_ids(self, provider_id: str) -> list[str]:
        base_id = self.get_model_id(provider_id)
        if not self.supports:
            return [base_id]
        return [f"{base_id}/{block}" for block in sorted(self.supports)]
