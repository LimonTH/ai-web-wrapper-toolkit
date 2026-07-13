from src.proxy.providers.base import BaseProviderAdapter
from src.proxy.providers.registry import register_adapter

"""
Adapter for v0.app (Vercel AI).
Minimal — all payload/extract logic lives in data/providers/v0.yaml.
Override methods here only for custom logic (e.g. RSC decoding).
"""


@register_adapter
class V0Adapter(BaseProviderAdapter):
    provider_id = "v0"
    provider_name = "V0 by Vercel"
    url_pattern = "v0.app"
    supports = {"chat"}
    # build_payload, extract_content, extract_stream_chunk — default, из YAML
