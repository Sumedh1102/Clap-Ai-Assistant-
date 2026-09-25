"""
Browser automation via Playwright (sync API).

A single persistent browser is reused across calls so pages stay open between
tool invocations within a session.

Playwright's sync API is bound to the thread that started it, while CLAP runs
commands on different threads (voice, web, scheduler). Every call is therefore
executed on one dedicated browser thread.

Google Chrome is used when installed; otherwise Playwright's bundled Chromium
(`playwright install chromium`).
"""

from __future__ import annotations

import concurrent.futures
import functools
import logging
import os
import tempfile
import time

log = logging.getLogger("clap.browser")

_THREAD_PREFIX = "clap-browser"
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix=_THREAD_PREFIX)

# Launch options (tests override these to run headless).
LAUNCH_OPTIONS: dict = {"headless": False, "args": ["--start-maximized"]}
PREFER_CHROME = True

_pw = None
_browser = None
_page = None

UNAVAILABLE = "Browser automation is unavailable"


def _on_browser_thread(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        import threading
        if threading.current_thread().name.startswith(_THREAD_PREFIX):
            return fn(*args, **kwargs)
        return _executor.submit(fn, *args, **kwargs).result()
    return wrapper


def _launch():
    global _pw
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")

    if _pw is None:
        _pw = sync_playwright().start()
    if PREFER_CHROME:
        try:
            return _pw.chromium.launch(channel="chrome", **LAUNCH_OPTIONS)
        except Exception as exc:
            log.info("Google Chrome unavailable (%s); using Playwright Chromium", str(exc).splitlines()[0])
    return _pw.chromium.launch(**LAUNCH_OPTIONS)


def _get_page():
    global _browser, _page
    if _page is not None and not _page.is_closed():
        return _page, None
    try:
        if _browser is None or not _browser.is_connected():
            _browser = _launch()
        _page = _browser.new_page()
        return _page, None
    except Exception as exc:
        log.exception("browser launch failed")
        reason = str(exc).splitlines()[0][:200]
        return None, f"{UNAVAILABLE}: {reason}"


@_on_browser_thread
def browser_navigate(url: str) -> dict:
    """Navigate to a URL."""
    page, err = _get_page()
    if err:
        return {"success": False, "error": err}
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        return {
            "success": True,
            "url": page.url,
            "title": page.title(),
            "status": response.status if response else None,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@_on_browser_thread
def browser_get_text(selector: str = "body") -> dict:
    """Extract visible text from the current page or a CSS selector."""
    page, err = _get_page()
    if err:
        return {"success": False, "error": err}
    try:
        el = page.locator(selector).first
        text = el.inner_text(timeout=10_000)
        # Truncate to avoid flooding the context
        if len(text) > 8000:
            text = text[:8000] + "\n… [truncated]"
        return {"success": True, "url": page.url, "selector": selector, "text": text}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@_on_browser_thread
def browser_click(selector: str = "", text: str = "") -> dict:
    """Click an element by CSS selector or by visible text."""
    page, err = _get_page()
    if err:
        return {"success": False, "error": err}
    try:
        if text:
            page.get_by_text(text, exact=False).first.click(timeout=10_000)
        elif selector:
            page.locator(selector).first.click(timeout=10_000)
        else:
            return {"success": False, "error": "Provide 'selector' or 'text'"}
        page.wait_for_load_state("domcontentloaded", timeout=10_000)
        return {"success": True, "url": page.url, "title": page.title()}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@_on_browser_thread
def browser_fill(selector: str, value: str, submit: bool = False) -> dict:
    """Fill an input field. Optionally press Enter to submit."""
    page, err = _get_page()
    if err:
        return {"success": False, "error": err}
    try:
        page.locator(selector).first.fill(value, timeout=10_000)
        if submit:
            page.keyboard.press("Enter")
            page.wait_for_load_state("domcontentloaded", timeout=10_000)
        return {"success": True, "url": page.url}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@_on_browser_thread
def browser_screenshot(path: str = "") -> dict:
    """Take a screenshot and save it (to a temp file when no path is given)."""
    page, err = _get_page()
    if err:
        return {"success": False, "error": err}
    try:
        if not path:
            path = os.path.join(tempfile.gettempdir(), f"clap-screenshot-{int(time.time())}.png")
        page.screenshot(path=path, full_page=False)
        return {"success": True, "saved_to": os.path.abspath(path), "url": page.url}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@_on_browser_thread
def browser_close() -> dict:
    """Close the browser."""
    global _browser, _page, _pw
    try:
        if _browser:
            _browser.close()
        if _pw:
            _pw.stop()
        return {"success": True, "message": "Browser closed"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        _browser = None
        _page = None
        _pw = None


@_on_browser_thread
def browser_current_url() -> dict:
    """Return the current page URL and title."""
    page, err = _get_page()
    if err:
        return {"success": False, "error": err}
    try:
        return {"success": True, "url": page.url, "title": page.title()}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
