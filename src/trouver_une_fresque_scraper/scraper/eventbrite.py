import numpy as np
import time
import json
import logging
import re

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from trouver_une_fresque_scraper.db.records import get_record_dict
from trouver_une_fresque_scraper.utils.date_and_time import get_dates_from_element
from trouver_une_fresque_scraper.utils.errors import (
    FreskError,
    FreskDateBadFormat,
)
from trouver_une_fresque_scraper.utils.keywords import (
    is_plenary,
    is_online,
    is_training,
)
from trouver_une_fresque_scraper.utils.language import detect_language_code
from trouver_une_fresque_scraper.utils.location import get_address
from trouver_une_fresque_scraper.utils.scraping import (
    managed_driver,
    retry_on_stale_element,
    safe_find_element,
    DEFAULT_TIMEOUT,
    PAGE_LOAD_DELAY,
    MAX_RETRIES,
)


def delete_cookies_overlay(driver):
    """Remove cookie consent overlay if present using safe element handling."""
    try:
        transcend_element = safe_find_element(
            driver, By.CSS_SELECTOR, "#transcend-consent-manager", timeout=DEFAULT_TIMEOUT
        )

        if transcend_element:
            driver.execute_script(
                "arguments[0].parentNode.removeChild(arguments[0]);", transcend_element
            )
            logging.debug("Cookie consent overlay removed")
    except Exception as e:
        logging.debug(f"Cookie consent overlay couldn't be removed: {e}")


@retry_on_stale_element(max_attempts=MAX_RETRIES)
def click_next_button(driver):
    """
    Safely click the 'Show More' button with retry logic.

    Scrolls the button into view and clicks it. Retries automatically
    if the element becomes stale.
    """
    next_button = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
        EC.element_to_be_clickable(
            (
                By.CSS_SELECTOR,
                "div.organizer-profile__section--content div.organizer-profile__show-more > button",
            )
        )
    )

    desired_y = (next_button.size["height"] / 2) + next_button.location["y"]
    window_h = driver.execute_script("return window.innerHeight")
    window_y = driver.execute_script("return window.pageYOffset")
    current_y = (window_h / 2) + window_y
    scroll_y_by = desired_y - current_y

    driver.execute_script("window.scrollBy(0, arguments[0]);", scroll_y_by)
    next_button.click()


def scroll_to_bottom(driver):
    """
    Scroll to bottom of page, clicking 'Show More' buttons with improved error handling.

    Continues scrolling and clicking until no more content can be loaded.
    Uses retry logic for stale elements.
    """
    more_content = True
    while more_content:
        logging.info("Scrolling to the bottom...")
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(5)  # Give the page some time to load new content

            # Try to click the next button with retry logic
            click_next_button(driver)

        except TimeoutException:
            # No more "Show More" button found
            more_content = False
            logging.debug("Reached end of content")
        except Exception as e:
            logging.warning(f"Error during scrolling: {e}")
            more_content = False


# ==================== Main Entry Point ====================


def get_eventbrite_data(sources, service, options):
    """
    Scrape EventBrite events with improved error handling and resource management.

    Uses context manager to ensure driver cleanup even if errors occur.

    Args:
        sources: List of source page configurations (dicts with 'id' and 'url')
        service: Selenium service instance
        options: Selenium options instance

    Returns:
        List of event records
    """
    logging.info("Scraping data from eventbrite.fr")

    # Use context manager for guaranteed cleanup
    with managed_driver(service, options) as driver:
        records = []

        for page in sources:
            try:
                logging.info(f"==================\nProcessing page {page}")
                driver.get(page["url"])

                # Scroll to bottom to load all events
                scroll_to_bottom(driver)
                driver.execute_script("window.scrollTo(0, 0);")

                # Find future events container with safe handling
                future_events = safe_find_element(
                    driver,
                    By.CSS_SELECTOR,
                    'div[data-testid="organizer-profile__future-events"]',
                    required=True,
                )

                event_card_divs = future_events.find_elements(By.CSS_SELECTOR, "div.event-card")
                logging.info(f"Found {len(event_card_divs)} events")

                # Extract links
                elements = []
                for event_card_div in event_card_divs:
                    link_elements = event_card_div.find_elements(
                        By.CSS_SELECTOR, "a.event-card-link"
                    )
                    elements.extend(link_elements)

                links = []
                for link_element in elements:
                    href = link_element.get_attribute("href")
                    if href:
                        links.append(href)
                links = np.unique(links)

                # Process each event
                for link in links:
                    try:
                        event_records = process_event_page(driver, link, page)
                        records.extend(event_records)
                    except Exception as e:
                        logging.error(f"Failed to process event {link}: {e}", exc_info=True)
                        continue

            except Exception as e:
                logging.error(
                    f"Failed to process organizer page {page.get('url', page)}: {e}", exc_info=True
                )
                continue

    return records


def process_event_page(driver, link, page):
    """
    Process a single event page with improved error handling.

    Args:
        driver: Selenium WebDriver instance
        link: URL of the event page
        page: Source page configuration dict

    Returns:
        List of event records (can be multiple for events with multiple dates)
    """
    logging.info(f"\n-> Processing {link} ...")
    records = []

    try:
        driver.get(link)
        delete_cookies_overlay(driver)
        time.sleep(PAGE_LOAD_DELAY)  # Pages are quite long to load

        ################################################################
        # Has it expired?
        ################################################################
        expired_badge = safe_find_element(
            driver, By.XPATH, '//div[@data-testid="enhancedExpiredEventsBadge"]', timeout=0
        )
        if expired_badge:
            # If the element has children elements, it is enabled
            if expired_badge.find_elements(By.XPATH, "./*"):
                logging.info("Rejecting record: event expired")
                return records

        # Check alternative expired badge
        alt_expired_badge = safe_find_element(
            driver, By.CSS_SELECTOR, "div.enhanced-expired-badge", timeout=0
        )
        if alt_expired_badge:
            logging.info("Rejecting record: event expired")
            return records

        ################################################################
        # Is it full?
        ################################################################
        sold_out = False
        sold_out_badge = safe_find_element(
            driver, By.XPATH, '//div[@data-testid="salesEndedMessage"]', timeout=0
        )

        if sold_out_badge:
            sold_out = bool(sold_out_badge.find_elements(By.XPATH, "./*"))

        if sold_out:
            # We reject sold out events as the Eventbrite UX hides
            # relevant info in this case (which looks like an awful practice)
            logging.info("Rejecting record: sold out")
            return records

        ################################################################
        # Parse event title
        ################################################################
        title_el = safe_find_element(driver, By.TAG_NAME, "h1", required=True)
        title = title_el.text

        if is_plenary(title):
            logging.info("Rejecting record: plénière")
            return records

        ###########################################################
        # Is it an online event?
        ################################################################
        online = is_online(title)
        if not online:
            short_location_el = safe_find_element(
                driver, By.CSS_SELECTOR, "span.start-date-and-location__location", timeout=0
            )
            if short_location_el:
                online = is_online(short_location_el.text)

        ################################################################
        # Location data
        ################################################################
        full_location = ""
        location_name = ""
        address = ""
        city = ""
        department = ""
        longitude = ""
        latitude = ""
        zip_code = ""
        country_code = ""

        if not online:
            full_location_el = safe_find_element(
                driver,
                By.CSS_SELECTOR,
                'div[class^="Location-module__addressWrapper___"',
                timeout=DEFAULT_TIMEOUT,
            )

            if not full_location_el:
                logging.error(f"Location element not found for offline event {link}.")
                return records

            full_location = full_location_el.text.replace("\n", ", ")

            try:
                address_dict = get_address(full_location)
                (
                    location_name,
                    address,
                    city,
                    department,
                    zip_code,
                    country_code,
                    latitude,
                    longitude,
                ) = address_dict.values()
            except FreskError as error:
                logging.info(f"Rejecting record: {error}.")
                return records

        ################################################################
        # Description
        ################################################################
        description_el = safe_find_element(
            driver, By.CSS_SELECTOR, "div.event-description", timeout=DEFAULT_TIMEOUT
        )

        if not description_el:
            logging.info("Rejecting record: Description not found.")
            return records

        description = description_el.text

        ################################################################
        # Training?
        ################################################################
        training = is_training(title)

        ################################################################
        # Is it suited for kids?
        ################################################################
        kids = False

        ################################################################
        # Multiple events
        ################################################################
        event_info = []

        # Try to find multiple date selector
        date_time_div = safe_find_element(
            driver, By.CSS_SELECTOR, "div.select-date-and-time", timeout=DEFAULT_TIMEOUT
        )

        if date_time_div:
            # Multiple events on this page
            driver.execute_script("window.scrollBy(0, arguments[0]);", 800)

            li_elements = date_time_div.find_elements(By.CSS_SELECTOR, "li:not([data-heap-id])")

            for li in li_elements:
                try:
                    clickable_li = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
                        EC.element_to_be_clickable(li)
                    )
                    clickable_li.click()

                    ################################################################
                    # Dates
                    ################################################################
                    date_info_el = safe_find_element(
                        driver, By.CSS_SELECTOR, "time.start-date-and-location__date", required=True
                    )

                    try:
                        event_start_datetime, event_end_datetime = get_dates_from_element(
                            date_info_el
                        )
                    except FreskDateBadFormat as error:
                        logging.info(f"Reject record: {error}")
                        continue

                    ################################################################
                    # Parse tickets link
                    ################################################################
                    tickets_link = driver.current_url

                    ################################################################
                    # Parse event id
                    ################################################################
                    uuid = re.search(r"/e/([^/?]+)", tickets_link).group(1)

                    # Selenium clicks on "sold out" cards (li elements), but this
                    # has no effect. Worse, this adds the previous non-sold out
                    # event another time. One can detect such cases by scanning
                    # through previous event ids.
                    already_scanned = False
                    for event in event_info:
                        if uuid in event[0]:
                            already_scanned = True

                    if not already_scanned:
                        event_info.append(
                            [
                                uuid,
                                event_start_datetime,
                                event_end_datetime,
                                tickets_link,
                            ]
                        )
                except Exception as e:
                    logging.warning(f"Failed to process date option: {e}")
                    continue
        else:
            # Single event on this page
            ################################################################
            # Single event with multiple dates (a "collection").
            ################################################################
            check_availability_btn = safe_find_element(
                driver, By.CSS_SELECTOR, "button.check-availability-btn__button", timeout=0
            )

            if check_availability_btn:
                # TODO: add support for this.
                logging.error(f"EventBrite collection not supported in event {link}.")
                return records

            ################################################################
            # Dates
            ################################################################
            date_info_el = safe_find_element(
                driver, By.CSS_SELECTOR, "time.start-date-and-location__date", required=True
            )

            try:
                event_start_datetime, event_end_datetime = get_dates_from_element(date_info_el)
            except FreskDateBadFormat as error:
                logging.info(f"Reject record: {error}")
                return records

            ################################################################
            # Parse tickets link
            ################################################################
            tickets_link = driver.current_url

            ################################################################
            # Parse event id
            ################################################################
            uuid = re.search(r"/e/([^/?]+)", tickets_link).group(1)

            event_info.append([uuid, event_start_datetime, event_end_datetime, tickets_link])

        ################################################################
        # Session loop
        ################################################################
        for index, (
            uuid,
            event_start_datetime,
            event_end_datetime,
            link,
        ) in enumerate(event_info):
            record = get_record_dict(
                f"{page['id']}-{uuid}",
                page["id"],
                title,
                event_start_datetime,
                event_end_datetime,
                full_location,
                location_name,
                address,
                city,
                department,
                zip_code,
                country_code,
                latitude,
                longitude,
                page.get(
                    "language_code",
                    detect_language_code(title, description),
                ),
                online,
                training,
                sold_out,
                kids,
                link,
                link,
                description,
            )
            records.append(record)
            logging.info(f"Successfully scraped {link}\n{json.dumps(record, indent=4)}")

    except Exception as e:
        logging.error(f"Unexpected error processing event page {link}: {e}", exc_info=True)

    return records
