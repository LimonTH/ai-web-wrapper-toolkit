from __future__ import annotations

from typing import Any

from playwright.async_api import async_playwright

from src.cookie_collector.browser import (
    _get_browser_args,
    _get_context_proxy,
    _setup_playwright_proxy_env,
    _cleanup_proxy_env,
    _create_context,
    _safe_close_browser,
)
from src.core.settings_service import get_settings_service

"""
Browser-based action recorder.
Opens a browser via Playwright, injects JS to intercept actions.
"""


async def record_actions(
        url: str,
        *,
        cookies: list[dict[str, Any]] | None = None,
        storage_state: dict[str, Any] | None = None,
        headless: bool = False,
        with_prompts: bool = True,
) -> list[dict[str, Any]]:
    """
    Opens a browser, injects JS interceptors, waits for the browser to close,
    returns a list of captured actions.
    """
    _svc = get_settings_service()
    browser_name = _svc.get_cached("playwright_browser") or "chromium"
    proxy_config = _get_context_proxy()

    _setup_playwright_proxy_env()

    captured: list[dict[str, Any]] = []
    pw = await async_playwright().start()
    browser = None
    context = None

    try:
        browser_type = getattr(pw, browser_name, pw.chromium)
        browser = await browser_type.launch(
            headless=headless,
            args=_get_browser_args(browser_name),
        )

        context = await _create_context(browser, storage_state, proxy_config=proxy_config, headless=headless)
        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()

        script = get_full_script(with_prompts=with_prompts)
        await page.add_init_script(script)

        _log_start(url, with_prompts)

        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        try:
            await page.wait_for_event("close", timeout=0)
        except Exception:
            pass

        try:
            captured = await page.evaluate(
                "JSON.parse(JSON.stringify(window.__recordedActions || []))"
            )
        except Exception as exc:
            print(f"⚠️ [recorder] Failed to extract actions: {exc}")

    except Exception as exc:
        print(f"⚠️ [recorder] Browser error: {type(exc).__name__}: {exc}")

    finally:
        await _safe_close_browser(browser, context)
        await pw.stop()
        _cleanup_proxy_env()

    _log_result(captured, with_prompts)
    return captured


def _log_start(url: str, with_prompts: bool) -> None:
    mode = "WITH DESCRIPTIONS" if with_prompts else "silent"
    print(f"\n🔍 Recording [{mode}] — {url}")
    print("👉 Every click / submit / Enter is captured.")
    if with_prompts:
        print("👉 For each action, two prompts will appear:")
        print("   1. What did you do?")
        print("   2. What happened as a result?")
    print("👉 Close the browser when done.\n")


def _log_result(captured: list[dict[str, Any]], with_prompts: bool) -> None:
    user_actions = [a for a in captured if a.get("type") != "api_response"]
    api_calls = [a for a in captured if a.get("type") == "api_response"]
    with_desc = sum(1 for a in user_actions if a.get("userDescription"))
    with_result = sum(1 for a in user_actions if a.get("resultDescription"))

    print(f"\n📊 Recorded: {len(user_actions)} user actions, {len(api_calls)} API calls")
    if with_prompts:
        print(f"📝 With descriptions: {with_desc}/{len(user_actions)}")
        print(f"📝 With result notes:  {with_result}/{len(user_actions)}")
