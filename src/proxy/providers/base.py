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
    - session: dict — mutable session context (chatId, parentId, etc.)
    """

    provider_id: str = ""
    provider_name: str = ""
    url_pattern: str = ""
    supports: set[str] = {"chat"}
    config: ProviderConfig | None = None
    # session is now instance-level (set in __init__), not a shared class variable

    def __init__(self) -> None:
        """Initialize adapter with a fresh per-instance session context."""
        self.session: dict[str, Any] = {}

    # ── Session lifecycle (multi-step providers) ────────────────────

    async def prepare_session(
        self,
        body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Initialize a session before the first request.
        Called once per conversation. Return a dict of session vars
        that will be merged into `self.session` and used by
        `${session.*}` in YAML body templates.

        `headers` contains the full HTTP headers including cookies
        from the cookie profile — useful for adapters that need
        to make auth-dependent API calls during session init.

        Default: no-op, returns {}.
        Override in adapters that need multi-step setup
        (e.g. v0: create chat project first).
        """
        return {}

    def extract_meta(self, response_headers: dict[str, str], response_body: Any) -> dict[str, Any]:
        """
        Extract session metadata from a response (headers + body).
        Called after each proxy request. Returned dict is merged into
        `self.session` so `${session.*}` references are updated.

        Default: no-op, returns {}.
        Override to capture e.g. parentId, nextUrl, tokens.
        """
        return {}

    # ── Config-driven defaults ─────────────────────────────────────

    def build_payload(
        self,
        endpoint_key: str,
        body: dict[str, Any],
        block: str = "chat",
    ) -> dict[str, Any]:
        """Default: delegates to ProviderConfig.build_body() with session context."""
        if self.config:
            return self.config.build_body(endpoint_key, body, session=self.session)
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
            "content-type": "application/json",
            "accept": "text/event-stream" if stream else "application/json",
            "user-agent": (
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
