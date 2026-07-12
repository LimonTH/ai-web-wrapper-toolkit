"""
Provider adapter registry with recursive auto-discovery.
Adapters are automatically discovered in providers/ and subfolders.
"""
import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Type

from src.core.models import WebsiteTemplate
from src.proxy.providers.base import BaseProviderAdapter
from src.proxy.providers.generic import GenericAdapter


class ProviderRegistry:
    """Registry of provider adapters with recursive auto-discovery."""

    def __init__(self):
        self._adapters: dict[str, Type[BaseProviderAdapter]] = {}
        self._default_adapter: Type[BaseProviderAdapter] = GenericAdapter
        self._discovered = False

    def _ensure_discovered(self) -> None:
        if self._discovered:
            return
        self._discovered = True
        package_path = Path(__file__).parent
        self._scan_dir(package_path, "src.proxy.providers")

    def _scan_dir(self, path: Path, prefix: str) -> None:
        for _importer, modname, is_pkg in pkgutil.iter_modules([str(path)]):
            if modname in ("__init__", "base", "registry"):
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
                        and obj is not GenericAdapter
                    ):
                        pid = getattr(obj, "provider_id", None)
                        if pid and pid not in self._adapters:
                            self._adapters[pid] = obj
                            print(f"  🔌 Discovered: {pid} ({obj.__name__})")
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

    def get_adapter(self, template: WebsiteTemplate) -> BaseProviderAdapter:
        """
        Returns an adapter for the given template.
        Priority: 1) provider_id 2) url_pattern 3) GenericAdapter.
        """
        self._ensure_discovered()
        slug = template.name.lower().replace(" ", "-").replace("_", "-")

        for pid, cls in self._adapters.items():
            if pid in slug or slug in pid:
                return cls()

        base_url = template.base_url.lower()
        for pid, cls in self._adapters.items():
            url_matcher = getattr(cls, "url_pattern", None)
            if url_matcher and url_matcher in base_url:
                return cls()

        return self._default_adapter()

    def list_providers(self) -> list[dict[str, str]]:
        self._ensure_discovered()
        return [
            {
                "id": cls.provider_id,
                "name": getattr(cls, "provider_name", cls.provider_id),
                "supports": list(getattr(cls, "supports", {"chat"})),
                "url_pattern": getattr(cls, "url_pattern", ""),
            }
            for cls in self._adapters.values()
        ]


_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry


def register_adapter(adapter_class: Type[BaseProviderAdapter]) -> Type[BaseProviderAdapter]:
    """Decorator for registering an adapter."""
    get_registry().register(adapter_class)
    return adapter_class