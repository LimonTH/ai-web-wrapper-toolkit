from src.proxy.providers.base import BaseProviderAdapter
from src.proxy.providers.registry import register_adapter

"""
Adapter for DeepSeek (deepseek.com).
Minimal — all payload/extract logic lives in data/providers/{provider_id}.yaml.
"""


@register_adapter
class DeepSeekAdapter(BaseProviderAdapter):
    provider_id = "deepseek"
    provider_name = "DeepSeek"
    url_pattern = "chat.deepseek.com"
    supports = {"chat"}
