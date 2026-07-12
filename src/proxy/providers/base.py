from abc import ABC, abstractmethod
from typing import Any

from src.core.models import WebsiteTemplate, ApiEndpoint

"""
Base provider adapter — plugin interface for site-specific API adapters.
Each site (ChatGPT, Claude, Gemini, etc.) has its own API format.
"""


class BaseProviderAdapter(ABC):
    """
    Base provider adapter class.

    Minimum required definitions:
    - provider_id: str
    - supports: set[str] — which functional_block values are supported

    And methods to implement:
    - get_endpoint(template, block, method) → ApiEndpoint | None
    - build_payload(endpoint, body, block) → dict
    - extract_content(data, block) → str
    - extract_stream_chunk(chunk_data, block) → str | None
    """

    provider_id: str = ""
    provider_name: str = ""
    url_pattern: str = ""  # URL substring for auto-mapping (e.g. "chat.openai.com")
    supports: set[str] = {"chat"}

    @abstractmethod
    def get_endpoint(
            self,
            template: WebsiteTemplate,
            block: str,
            method: str = "POST",
    ) -> ApiEndpoint | None:
        """Returns an endpoint for the specified functional_block."""
        ...

    @abstractmethod
    def build_payload(
            self,
            endpoint: ApiEndpoint,
            body: dict[str, Any],
            block: str = "chat",
    ) -> dict[str, Any]:
        """Converts OpenAI request format to the site's format."""
        ...

    @abstractmethod
    def extract_content(
            self,
            data: dict[str, Any] | str | list,
            block: str = "chat",
    ) -> str:
        """Extracts text/content from the site's response."""
        ...

    @abstractmethod
    def extract_stream_chunk(
            self,
            chunk_data: dict[str, Any],
            block: str = "chat",
    ) -> str | None:
        """Extracts text from a single SSE streaming chunk."""
        ...

    def get_headers(
            self,
            template: WebsiteTemplate,
            stream: bool = False,
            block: str = "chat",
    ) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            ),
        }
        if template.default_headers:
            headers.update(template.default_headers)
        return headers

    def get_model_id(self, template: WebsiteTemplate) -> str:
        return template.name.lower().replace(" ", "-").replace("_", "-")

    def get_model_ids(self, template: WebsiteTemplate) -> list[str]:
        base_id = self.get_model_id(template)
        if not self.supports:
            return [base_id]
        return [f"{base_id}/{block}" for block in sorted(self.supports)]
