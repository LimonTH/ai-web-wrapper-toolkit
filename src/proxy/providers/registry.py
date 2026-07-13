import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Type

from src.providers.config import (
    ProviderConfig,
    load_all_provider_configs,
)
from src.proxy.providers.base import BaseProviderAdapter

"""
Provider adapter registry with YAML-driven provider discovery.
- Scans data/providers/*.yaml for provider configs
- Discovers adapter classes for custom overrides
- ProviderConfig is the single source of truth
"""


class ProviderRegistry:
    """Registry of provider configs + adapters."""

    def __init__(self):
        self._adapters: dict[str, Type[BaseProviderAdapter]] = {}
        self._configs: dict[str, ProviderConfig] = {}
        self._discovered = False

    def _ensure_discovered(self) -> None:
        if self._discovered:
            return
        self._discovered = True

        # 1. Load YAML configs first (single source of truth)
        self._configs = load_all_provider_configs()
        for pid in self._configs:
            print(f"  📄 Loaded config: {pid}")

        # 2. Discover adapter classes (for custom method overrides)
        package_path = Path(__file__).parent
        self._scan_dir(package_path, "src.proxy.providers")

    def _scan_dir(self, path: Path, prefix: str) -> None:
        for _importer, modname, is_pkg in pkgutil.iter_modules([str(path)]):
            if modname in ("__init__", "base", "registry", "generic"):
                continue
            if is_pkg:
                self._scan_dir(path / modname, f"{prefix}.{modname}")
                continue
            try:
                mod = importlib.import_module(f"{prefix}.{modname}")
                for _name, obj in inspect.getmembers(mod, inspect.isclass):
                    if (
                        obj is not BaseProviderAdapter
                        and issubclass(obj, BaseProviderAdapter)
                    ):
                        pid = getattr(obj, "provider_id", None)
                        if pid and pid not in self._adapters:
                            self._adapters[pid] = obj
                        if pid:
                            print(f"  🔌 Adapter: {pid} ({obj.__name__})")
            except Exception:
                pass

    def register(self, adapter_class: Type[BaseProviderAdapter]) -> None:
        if not issubclass(adapter_class, BaseProviderAdapter):
            raise TypeError(
                f"{adapter_class.__name__} must inherit from BaseProviderAdapter"
            )
        provider_id = getattr(adapter_class, "provider_id", None)
        if not provider_id:
            raise ValueError(f"{adapter_class.__name__} must define 'provider_id'")
        self._adapters[provider_id] = adapter_class

    # ── Config access ──────────────────────────────────────────────

    def get_config(self, provider_id: str) -> ProviderConfig | None:
        """Get ProviderConfig by provider_id."""
        self._ensure_discovered()
        return self._configs.get(provider_id)

    def get_adapter(self, provider_id: str) -> BaseProviderAdapter:
        """
        Get adapter instance by provider_id.
        Attaches ProviderConfig to adapter if available.
        Falls back to a bare adapter with config-only if no class registered.
        """
        self._ensure_discovered()
        cls = self._adapters.get(provider_id)
        config = self._configs.get(provider_id)

        if cls:
            adapter = cls()
        else:
            adapter = BaseProviderAdapter()
            adapter.provider_id = provider_id
            adapter.provider_name = config.name if config else provider_id

        adapter.config = config
        if config:
            adapter.supports = config.supports

        return adapter

    # ── Legacy: backward-compat get_adapter(template) ──────────────

    def get_adapter_by_template(self, template) -> BaseProviderAdapter:
        """
        Legacy method: resolves adapter from a template-like object.
        Uses template.name as provider_id, falls back to url_pattern matching.
        """
        self._ensure_discovered()
        slug = template.name.lower().replace(" ", "-").replace("_", "-")

        # Try name-based match first
        for pid in self._configs:
            if pid in slug or slug in pid:
                return self.get_adapter(pid)

        for pid, cls in self._adapters.items():
            if pid in slug or slug in pid:
                return self.get_adapter(pid)

        # Try URL pattern match
        base_url = getattr(template, "base_url", "").lower()
        for pid, cls in self._adapters.items():
            url_matcher = getattr(cls, "url_pattern", None)
            if url_matcher and url_matcher in base_url:
                return self.get_adapter(pid)

        # Fallback: return generic adapter with no config
        from src.proxy.providers.generic import GenericAdapter
        return GenericAdapter()

    # ── Listing ────────────────────────────────────────────────────

    def list_providers(self) -> list[dict[str, str]]:
        """List all known providers from YAML configs."""
        self._ensure_discovered()
        return [
            {
                "id": pid,
                "name": config.name,
                "supports": list(config.supports),
                "url_pattern": getattr(
                    self._adapters.get(pid), "url_pattern", ""
                ),
            }
            for pid, config in self._configs.items()
        ]


_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry


def register_adapter(
    adapter_class: Type[BaseProviderAdapter],
) -> Type[BaseProviderAdapter]:
    """Decorator for registering an adapter."""
    get_registry().register(adapter_class)
    return adapter_class
