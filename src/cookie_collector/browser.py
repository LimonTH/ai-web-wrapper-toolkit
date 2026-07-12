import os
from typing import Any

from playwright.async_api import async_playwright

from src.core.settings_service import get_settings_service

"""
Playwright browser automation with full stealth anti-detection for Google OAuth.
"""

_REAL_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--ignore-certificate-errors",
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--window-size=1920,1080",
]

_FIREFOX_ARGS: list[str] = []

_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => false });
window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
    Promise.resolve({ state: Notification.permission }) :
    originalQuery(parameters)
);
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
"""

_PW_TARGET_CLOSED = "TargetClosedError"
_PW_TIMEOUT = "TimeoutError"

_CLOSED = object()


def _get_browser_args(browser_name: str = "chromium") -> list[str]:
    """Browser launch arguments. Chromium flags are not passed to Firefox/WebKit."""
    _svc = get_settings_service()
    if browser_name == "chromium":
        args = list(_CHROMIUM_ARGS)
        proxy = _svc.proxy_for_browser
        if proxy:
            args.append(f"--proxy-server={proxy}")
            bypass = _svc.get_cached("proxy_bypass_domains")
            if bypass:
                args.append(f"--proxy-bypass-list={bypass}")
        return args

    return list(_FIREFOX_ARGS)


def _get_context_proxy() -> dict | None:
    """Returns proxy config for Playwright browser context."""
    _svc = get_settings_service()
    proxy = _svc.proxy_for_browser
    if not proxy:
        return None
    config: dict[str, str] = {"server": proxy}
    bypass = _svc.get_cached("proxy_bypass_domains")
    if bypass:
        config["bypass"] = bypass
    return config


def _cleanup_proxy_env() -> None:
    """Cleans up proxy environment variables after browser work."""
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(key, None)


def _setup_playwright_proxy_env() -> None:
    """Sets proxy environment variables for Playwright browser launch."""
    _svc = get_settings_service()
    proxy = _svc.proxy_for_browser
    if proxy:
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy
        os.environ["NO_PROXY"] = "localhost,127.0.0.1"


def _pw_safe(coro, label: str = "operation", default=None):
    """Unified safe-wrapper for Playwright coroutines."""
    try:
        return coro
    except Exception as e:
        err_name = type(e).__name__
        print(f"⚠️ [{label}] {err_name}: {e}")
        return default


async def _create_context(browser, storage_state=None, proxy_config: dict | None = None, headless: bool = False):
    """Creates a browser context with proxy support for all browser types."""
    context_kwargs: dict[str, Any] = {
        "ignore_https_errors": True,
        "user_agent": _REAL_UA,
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "storage_state": storage_state or {},
    }

    if headless:
        context_kwargs["viewport"] = {"width": 1920, "height": 1080}
    else:
        context_kwargs["no_viewport"] = True

    if proxy_config:
        context_kwargs["proxy"] = proxy_config

    context = await browser.new_context(**context_kwargs)
    await context.add_init_script(_STEALTH_SCRIPT)
    context.set_default_navigation_timeout(60000)
    return context


async def _safe_goto(page, url: str, timeout: int = 60000) -> None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    except Exception as e:
        print(f"⚠️ [navigation] {type(e).__name__}: {e}")


async def _safe_evaluate(page, expression: str, default: Any = "") -> Any:
    """Safe evaluate. Returns _CLOSED on TargetClosedError."""
    try:
        return await page.evaluate(expression)
    except Exception as e:
        err_name = type(e).__name__
        if err_name == _PW_TARGET_CLOSED:
            return _CLOSED
        return default


async def _safe_wait_for_timeout(page, ms: int) -> None:
    try:
        await page.wait_for_timeout(ms)
    except Exception as e:
        err_name = type(e).__name__
        if err_name in (_PW_TARGET_CLOSED, _PW_TIMEOUT):
            pass
        else:
            print(f"⚠️ [wait_for_timeout] {err_name}: {e}")


async def _safe_close_browser(browser, context=None) -> None:
    if context:
        try:
            await context.close()
        except Exception:
            pass
    if browser:
        try:
            await browser.close()
        except Exception:
            pass


async def login_and_get_cookies(
        template_name: str,
        login_url: str | None = None,
        headless: bool = False,
        auto_close: bool = True,
) -> dict[str, Any]:
    """Opens browser, auto-detects login via Python-side text polling."""
    import asyncio

    LOGIN_WORDS = [
        'log in', 'login', 'sign in', 'signin', 'sign up', 'signup',
        'register', 'registration', 'create account', 'get started',
        'subscribe', 'continue with', 'start free'
    ]

    _svc = get_settings_service()
    browser_name = _svc.get_cached("playwright_browser")
    proxy_config = _get_context_proxy()
    _setup_playwright_proxy_env()
    from playwright.async_api import async_playwright

    p = await async_playwright().start()
    browser = None
    context = None
    try:
        browser_type = getattr(p, browser_name, p.chromium)
        browser = await browser_type.launch(
            headless=headless,
            args=_get_browser_args(browser_name),
        )
        context = await _create_context(browser, proxy_config=proxy_config, headless=headless)
        page = await context.new_page()

        if login_url:
            await _safe_goto(page, login_url)

        await _safe_wait_for_timeout(page, 3000)

        def has_login(text: str) -> bool:
            t = text.lower()
            if 'accept all cookies' in t or 'cookie settings' in t:
                return False
            return any(w in t for w in LOGIN_WORDS)

        was_login = False
        text = await _safe_evaluate(page, "document.body?.innerText?.toLowerCase() || ''")
        if text is not _CLOSED and text:
            was_login = has_login(text)

        print(f"\n🔐 Browser opened for {template_name}")
        print("👉 Sign in. Browser auto-closes once logged in.\n")

        logged_in = False
        for i in range(150):
            text = await _safe_evaluate(page, "document.body?.innerText?.toLowerCase() || ''")
            if text is _CLOSED:
                print("⚠️ Browser was closed by user")
                break
            if text:
                is_login = has_login(text)
                if was_login and not is_login:
                    print("✅ Login detected! Saving cookies...")
                    logged_in = True
                    break
                if is_login:
                    was_login = True

            try:
                await asyncio.wait_for(
                    page.wait_for_event("close", timeout=2_000), timeout=2_000
                )
                break
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                if type(e).__name__ == _PW_TARGET_CLOSED:
                    break
                continue

        cookies = await context.cookies() if context else []
        storage = await context.storage_state() if context else {}
        return {
            "cookies": cookies if logged_in else None,
            "storage_state": storage if logged_in else None,
            "logged_in": logged_in,
        }
    finally:
        await _safe_close_browser(browser, context)
        await p.stop()
        _cleanup_proxy_env()


async def inject_cookies_and_open(
        url: str,
        cookies: list[dict[str, Any]],
        storage_state: dict[str, Any] | None = None,
        headless: bool = True,
) -> None:
    """Opens a site with injected cookies for testing."""
    _svc = get_settings_service()
    browser_name = _svc.get_cached("playwright_browser")
    proxy_config = _get_context_proxy()
    _setup_playwright_proxy_env()

    p = await async_playwright().start()
    browser = None
    context = None
    try:
        browser_type = getattr(p, browser_name, p.chromium)
        browser = await browser_type.launch(
            headless=headless,
            args=_get_browser_args(browser_name),
        )
        context = await _create_context(browser, storage_state, proxy_config=proxy_config, headless=headless)
        if cookies:
            await context.add_cookies(cookies)
        page = await context.new_page()
        await _safe_goto(page, url)
        print(f"✅ Opened {url}")
        await _safe_wait_for_timeout(page, 30000)
    finally:
        await _safe_close_browser(browser, context)
        await p.stop()
        _cleanup_proxy_env()
