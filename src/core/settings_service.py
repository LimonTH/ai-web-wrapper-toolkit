"""
Runtime settings service — hot-reloadable settings in the database.
Can be changed via UI without server restart.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import AppSetting

_DEFAULTS: dict[str, str] = {
    "proxy_url": "",
    "proxy_scope": "none",
    "proxy_bypass_domains": (
        "accounts.google.com,google.com,github.com,microsoftonline.com,"
        "apple.com,facebook.com,twitter.com,x.com,oauth2.googleapis.com,"
        "login.microsoftonline.com,appleid.apple.com,amazon.com,"
        "login.live.com,dropbox.com,discord.com,gitlab.com"
    ),
    "playwright_browser": "chromium",
}

UI_VISIBLE_KEYS = [
    "proxy_url",
    "proxy_scope",
    "proxy_bypass_domains",
    "playwright_browser",
]


class SettingsService:
    """Caching settings service with auto-loading from the database."""

    def __init__(self):
        self._cache: dict[str, str] = {}
        self._loaded = False

    async def _ensure_loaded(self, db: AsyncSession) -> None:
        """Lazy-load the cache from the database on first access."""
        if self._loaded:
            return
        result = await db.execute(select(AppSetting))
        for row in result.scalars():
            self._cache[row.key] = row.value
        self._loaded = True

    async def get(self, key: str, db: AsyncSession | None = None) -> str:
        if db is not None:
            await self._ensure_loaded(db)
        return self._cache.get(key, _DEFAULTS.get(key, ""))

    def get_cached(self, key: str) -> str:
        """Synchronous read from cache (no database). Cache must be pre-loaded."""
        return self._cache.get(key, _DEFAULTS.get(key, ""))

    async def get_bool(self, key: str, db: AsyncSession | None = None) -> bool:
        val = await self.get(key, db)
        return val.lower() in ("true", "1", "yes")

    async def set(self, key: str, value: str, db: AsyncSession) -> None:
        """Save setting to the database + update cache (upsert)."""
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(AppSetting).values(key=key, value=value)
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={"value": value},
        )
        await db.execute(stmt)
        self._cache[key] = value

    async def get_all(self, db: AsyncSession) -> dict[str, str]:
        await self._ensure_loaded(db)
        result = {}
        for k, v in _DEFAULTS.items():
            result[k] = self._cache.get(k, v)
        result.update(self._cache)
        return result

    async def get_ui_settings(self, db: AsyncSession) -> dict[str, str]:
        all_settings = await self.get_all(db)
        return {k: all_settings[k] for k in UI_VISIBLE_KEYS if k in all_settings}

    async def reload(self, db: AsyncSession) -> None:
        self._cache.clear()
        self._loaded = False
        await self._ensure_loaded(db)

    @property
    def proxy_for_browser(self) -> str | None:
        proxy = self._cache.get("proxy_url", _DEFAULTS.get("proxy_url", ""))
        scope = self._cache.get("proxy_scope", _DEFAULTS.get("proxy_scope", "none"))
        if proxy and scope in ("browser", "both"):
            return proxy
        return None

    @property
    def proxy_for_app(self) -> str | None:
        proxy = self._cache.get("proxy_url", _DEFAULTS.get("proxy_url", ""))
        scope = self._cache.get("proxy_scope", _DEFAULTS.get("proxy_scope", "none"))
        if proxy and scope in ("app", "both"):
            return proxy
        return None


_settings_service: SettingsService | None = None


def get_settings_service() -> SettingsService:
    global _settings_service
    if _settings_service is None:
        _settings_service = SettingsService()
    return _settings_service