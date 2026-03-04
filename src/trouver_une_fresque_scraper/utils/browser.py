import logging
from contextlib import contextmanager

from playwright.sync_api import sync_playwright


DEFAULT_TIMEOUT = 10000  # milliseconds


@contextmanager
def managed_browser(headless=False):
    """Context manager for Playwright browser.

    Yields a Chromium browser instance managed by Playwright.
    Ensures proper cleanup of both browser and Playwright on exit.
    """
    playwright = None
    browser = None
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=headless)
        logging.info("Playwright browser initialized successfully")
        yield browser
    finally:
        if browser:
            browser.close()
            logging.info("Browser closed successfully")
        if playwright:
            playwright.stop()
