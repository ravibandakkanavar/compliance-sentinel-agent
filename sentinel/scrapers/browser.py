"""Playwright helpers shared by the web adapters."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import Browser, BrowserContext, sync_playwright

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@contextmanager
def browser_context() -> Iterator[BrowserContext]:
    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="en-GB")
        try:
            yield context
        finally:
            context.close()
            browser.close()


def fetch_html(url: str, wait_for: str | None = None, timeout_ms: int = 60_000) -> str:
    """Load a page in a real browser and return the rendered HTML.

    A browser is needed because some portals answer plain HTTP clients with a
    JavaScript challenge page instead of the document.
    """
    with browser_context() as context:
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        if wait_for:
            page.wait_for_selector(wait_for, timeout=timeout_ms)
        return page.content()


def fetch_bytes(url: str, timeout_ms: int = 120_000) -> bytes:
    """Download a file (for example a PDF) through the browser's network stack."""
    with browser_context() as context:
        response = context.request.get(url, timeout=timeout_ms)
        if not response.ok:
            raise RuntimeError(f"GET {url} returned HTTP {response.status}")
        return response.body()
