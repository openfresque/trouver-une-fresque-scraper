import logging
from contextlib import contextmanager

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth


DEFAULT_TIMEOUT = 10000  # milliseconds

# Stealth instance configured for French locale (most HelloAsso users are French).
# Automatically patches navigator.webdriver, user-agent, plugins, WebGL, etc.
_stealth = Stealth(
    navigator_languages_override=("fr-FR", "fr"),
)


@contextmanager
def managed_browser(headless=False):
    """Context manager for a stealth Playwright browser.

    Uses playwright-stealth to hide automation signals (navigator.webdriver,
    headless indicators, etc.) so that Cloudflare Turnstile and similar
    challenges are less likely to trigger.

    Yields a Chromium browser instance managed by Playwright.
    Ensures proper cleanup of both browser and Playwright on exit.
    """
    with _stealth.use_sync(sync_playwright()) as playwright:
        browser = playwright.chromium.launch(headless=headless)
        logging.info("Playwright stealth browser initialized successfully")
        try:
            yield browser
        finally:
            browser.close()
            logging.info("Browser closed successfully")
