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
from trouver_une_fresque_scraper.utils.date_and_time import get_dates_from_element, get_dates
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
    Scrape EventBrite events with proper waits.

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
                    event_records = process_event_page(driver, link, page)
                    records.extend(event_records)

            except Exception as e:
                logging.error(
                    f"Failed to process organizer page {page.get('url', page)}: {e}", exc_info=True
                )
                raise

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
        # tbouvier: I think that this selector is actually obsolete. This was refering to
        # a carousel of dates that EventBrite used to have a while ago.
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
                driver, By.CSS_SELECTOR, "button[id^='check-availability-btn-']", timeout=0
            )

            if check_availability_btn:
                # Click the button to open the modal
                try:
                    logging.info("Found EventBrite collection, clicking availability button...")
                    check_availability_btn.click()

                    # Wait for modal to load by waiting for first date wrapper element to appear
                    logging.debug("Waiting for modal to load...")
                    time.sleep(PAGE_LOAD_DELAY)  # Give initial time for modal animation

                    # Switch to iframe if modal content is in an iframe
                    iframe = safe_find_element(
                        driver,
                        By.CSS_SELECTOR,
                        'iframe[id*="eventbrite-widget"], iframe[class*="modal"], iframe[title*="availability"]',
                        timeout=DEFAULT_TIMEOUT,
                        required=False,
                    )
                    if iframe:
                        logging.debug("Switching to iframe for modal content...")
                        driver.switch_to.frame(iframe)

                    ################################################################
                    # Check which type of modal we have
                    ################################################################

                    # Type 1: Simple list with date wrappers (one or more dates with time slots shown)
                    date_wrappers = driver.find_elements(By.CSS_SELECTOR, 'p[class*="dateWrapper"]')
                    # Type 2: Calendar/carousel with clickable date cards
                    calendar_date_cards = driver.find_elements(
                        By.CSS_SELECTOR,
                        'div[class*="CompactCalendar"] div[class*="compactChoiceCardContainer"]',
                    )

                    if calendar_date_cards:
                        ################################################################
                        # Handle calendar-style modal (Type 2)
                        ################################################################
                        logging.info(
                            f"Found calendar-style modal with {len(calendar_date_cards)} date cards"
                        )

                        # Process each date card in the calendar
                        for card_index, date_card in enumerate(calendar_date_cards):
                            try:
                                # Extract date information from the card before clicking
                                weekday_el = date_card.find_element(
                                    By.CSS_SELECTOR, 'p[class*="weekday"]'
                                )
                                day_num_el = date_card.find_element(
                                    By.CSS_SELECTOR, 'p[class*="dateText"]'
                                )
                                time_slot_el = date_card.find_element(
                                    By.CSS_SELECTOR, 'p[class*="timeSlot"]'
                                )

                                weekday = weekday_el.text  # e.g., "SAT"
                                day_num = day_num_el.text  # e.g., "24"
                                time_slot = time_slot_el.text  # e.g., "9:00 am"

                                # Get the month by finding the parent CompactCalendar_compactDateGrid
                                # and then looking for the preceding monthName sibling
                                month = "Unknown"
                                try:
                                    # Navigate to the parent grid container
                                    date_grid = date_card.find_element(
                                        By.XPATH,
                                        "./ancestor::div[contains(@class, 'compactDateGrid')]",
                                    )
                                    # Get the parent Stack_root that contains both month name and grid
                                    stack_parent = date_grid.find_element(By.XPATH, "./parent::div")
                                    # Find the month name in the same parent
                                    month_header = stack_parent.find_element(
                                        By.CSS_SELECTOR, 'p[class*="monthName"]'
                                    )
                                    month = month_header.text  # e.g., "January"
                                except Exception as e:
                                    logging.debug(f"Could not find month header: {e}")

                                logging.debug(
                                    f"Processing calendar date: {weekday}, {month} {day_num} at {time_slot}"
                                )

                                # Format the date string for parsing
                                # e.g., "SAT, January 24 9:00 am"
                                date_str = f"{weekday}, {month} {day_num} {time_slot}"

                                try:
                                    # Parse the date - we may need to add end time logic
                                    # For now, assume default duration if no end time
                                    event_start_datetime, event_end_datetime = get_dates(date_str)
                                except FreskDateBadFormat as error:
                                    logging.warning(
                                        f"Failed to parse calendar date '{date_str}': {error}"
                                    )
                                    continue

                                # Generate UUID
                                base_uuid = re.search(r"/e/([^/?]+)", link).group(1)
                                unique_suffix = hash(date_str) % 10000
                                uuid = f"{base_uuid}-{unique_suffix}"

                                event_info.append(
                                    [
                                        uuid,
                                        event_start_datetime,
                                        event_end_datetime,
                                        link,
                                    ]
                                )
                                logging.debug(f"Added calendar event: {uuid}")

                            except Exception as e:
                                logging.warning(
                                    f"Failed to process calendar date card {card_index + 1}: {e}"
                                )
                                continue

                    elif date_wrappers:
                        ################################################################
                        # Handle simple list modal (Type 1)
                        ################################################################
                        logging.info(f"Found {len(date_wrappers)} dates in list-style modal")

                        # Process each date
                        for date_wrapper in date_wrappers:
                            try:
                                date_text = date_wrapper.text
                                logging.debug(f"Processing date: {date_text}")

                                # Click on the date wrapper or its parent card to reveal time slots
                                try:
                                    # Try to find the clickable parent (EventInfoCard or similar)
                                    clickable_parent = date_wrapper.find_element(
                                        By.XPATH,
                                        "./ancestor::div[contains(@class, 'EventInfoCard')]",
                                    )
                                    clickable_parent.click()
                                    logging.debug(f"Clicked on date card for: {date_text}")

                                    # Wait for time slots to load - use explicit wait for time slot list to appear
                                    logging.debug("Waiting for time slots to load...")
                                    time_slot_list_loaded = safe_find_element(
                                        driver,
                                        By.CSS_SELECTOR,
                                        'ul[class*="TimeSlotList"]',
                                        timeout=DEFAULT_TIMEOUT,
                                        required=False,
                                    )

                                    if not time_slot_list_loaded:
                                        logging.warning(
                                            f"Time slot list did not load for date: {date_text}"
                                        )
                                        continue

                                    # Give extra time for all content to render
                                    time.sleep(2)

                                except Exception as e:
                                    logging.debug(f"Could not click date card: {e}")

                                # Find the time slots - search more broadly in the entire iframe/modal
                                # Look for TimeSlotList ul elements in the entire document
                                all_time_slot_lists = driver.find_elements(
                                    By.CSS_SELECTOR, 'ul[class*="TimeSlotList"]'
                                )

                                if not all_time_slot_lists:
                                    logging.warning(
                                        f"No time slot lists found for date: {date_text}"
                                    )
                                    continue

                                logging.debug(
                                    f"Found {len(all_time_slot_lists)} time slot lists in modal"
                                )

                                # Extract time slot data immediately to avoid stale element issues
                                time_slots_data = []
                                for time_slot_list in all_time_slot_lists:
                                    time_slot_lis = time_slot_list.find_elements(By.TAG_NAME, "li")
                                    for time_slot_li in time_slot_lis:
                                        try:
                                            # Extract text immediately before DOM can change
                                            time_element = time_slot_li.find_element(
                                                By.CSS_SELECTOR, 'p[class*="sessionText"]'
                                            )
                                            time_text = time_element.text
                                            if time_text:  # Only add if we got actual text
                                                time_slots_data.append(time_text)
                                        except Exception as e:
                                            logging.debug(f"Could not extract time slot text: {e}")
                                            continue

                                if not time_slots_data:
                                    logging.warning(f"No time slots found for date: {date_text}")
                                    continue

                                logging.debug(
                                    f"Found {len(time_slots_data)} time slots for date: {date_text}"
                                )

                                # Process each time slot for this date
                                for time_text in time_slots_data:
                                    try:
                                        logging.debug(f"Processing time slot: {time_text}")

                                        # Combine date and time for parsing
                                        # Format: "Sat, Feb 14 9:00 am - 12:30 pm"
                                        combined_text = f"{date_text} {time_text}"

                                        try:
                                            # Use get_dates directly to parse the text
                                            event_start_datetime, event_end_datetime = get_dates(
                                                combined_text
                                            )
                                        except FreskDateBadFormat as error:
                                            logging.warning(
                                                f"Failed to parse date '{combined_text}': {error}"
                                            )
                                            continue

                                        # Generate a unique UUID for this specific date/time combo
                                        base_uuid = re.search(r"/e/([^/?]+)", link).group(1)
                                        # Create unique ID by combining base UUID with date/time hash
                                        unique_suffix = hash(combined_text) % 10000
                                        uuid = f"{base_uuid}-{unique_suffix}"

                                        event_info.append(
                                            [
                                                uuid,
                                                event_start_datetime,
                                                event_end_datetime,
                                                link,
                                            ]
                                        )
                                        logging.debug(f"Added event: {uuid}")

                                    except Exception as e:
                                        logging.warning(
                                            f"Failed to process time slot '{time_text}': {e}"
                                        )
                                        continue

                            except Exception as e:
                                logging.warning(f"Failed to process date wrapper: {e}")
                                continue
                    if not event_info:
                        logging.error(f"No valid events extracted from collection for {link}.")
                        driver.switch_to.default_content()
                        return records

                    # Switch back to default content after processing modal
                    driver.switch_to.default_content()
                    logging.debug("Switched back to default content")

                except Exception as e:
                    logging.error(
                        f"Failed to process EventBrite collection for {link}: {e}", exc_info=True
                    )
                    # Make sure to switch back even on error
                    driver.switch_to.default_content()
                    return records
            else:
                # Regular single event
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
