import logging
import time

from contextlib import contextmanager
from functools import wraps
from typing import Optional

from selenium import webdriver
from selenium.common.exceptions import (
    StaleElementReferenceException,
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC


DEFAULT_TIMEOUT = 10
IMPLICIT_WAIT = 3
PAGE_LOAD_DELAY = 3
MAX_RETRIES = 3
RETRY_DELAY = 1


def retry_on_stale_element(max_attempts=MAX_RETRIES):
    """
    Decorator to retry function calls when StaleElementReferenceException occurs.

    This handles cases where the DOM changes between finding an element and interacting with it.

    Args:
        max_attempts: Maximum number of retry attempts (default: 3)
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except StaleElementReferenceException as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        logging.warning(
                            f"Stale element in {func.__name__}, "
                            f"retrying ({attempt + 1}/{max_attempts})..."
                        )
                        time.sleep(RETRY_DELAY)
                    else:
                        logging.error(f"Failed after {max_attempts} attempts in {func.__name__}")
            raise last_exception

        return wrapper

    return decorator


@contextmanager
def managed_driver(service, options):
    """
    Context manager for WebDriver that ensures proper cleanup.

    Guarantees that the driver will be quit even if exceptions occur during scraping.

    Args:
        service: Selenium service instance
        options: Selenium options instance

    Yields:
        WebDriver instance

    Example:
        with managed_driver(service, options) as driver:
            driver.get(url)
            # ... scraping code ...
        # driver.quit() is automatically called
    """
    driver = None
    try:
        driver = webdriver.Firefox(service=service, options=options)
        driver.implicitly_wait(IMPLICIT_WAIT)
        logging.info("WebDriver initialized successfully")
        yield driver
    except Exception as e:
        logging.error(f"Error during WebDriver operation: {e}", exc_info=True)
        raise
    finally:
        if driver:
            try:
                driver.quit()
                logging.info("WebDriver closed successfully")
            except Exception as e:
                logging.error(f"Error closing WebDriver: {e}")


def safe_find_element(
    driver, by, value, timeout=DEFAULT_TIMEOUT, required=False
) -> Optional[WebElement]:
    """
    Safely find an element with configurable timeout and error handling.

    This wrapper provides:
    - Configurable explicit waits
    - Optional vs required element behavior
    - Consistent error handling and logging
    - Returns None for optional elements not found

    Args:
        driver: Selenium WebDriver instance
        by: Selenium By locator type (e.g., By.CSS_SELECTOR, By.XPATH)
        value: Selector value
        timeout: Maximum wait time in seconds (0 for no wait, default: 10)
        required: If True, raises exception when element not found (default: False)

    Returns:
        WebElement if found, None if optional and not found

    Raises:
        NoSuchElementException: If required=True and element not found
        TimeoutException: If required=True and element not found within timeout

    Example:
        # Optional element
        badge = safe_find_element(driver, By.CSS_SELECTOR, ".badge", timeout=5)
        if badge:
            print(badge.text)

        # Required element
        title = safe_find_element(driver, By.TAG_NAME, "h1", required=True)
        print(title.text)  # Will never be None
    """
    try:
        if timeout > 0:
            element = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            return element
        else:
            return driver.find_element(by, value)
    except (TimeoutException, NoSuchElementException):
        if required:
            logging.error(f"Required element not found: {value}")
            raise
        logging.debug(f"Optional element not found: {value}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error finding element {value}: {e}")
        if required:
            raise
        return None
