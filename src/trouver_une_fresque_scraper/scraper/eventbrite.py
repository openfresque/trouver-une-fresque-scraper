import numpy as np
import json
import logging
import re
from contextlib import contextmanager

from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeoutError

from trouver_une_fresque_scraper.db.records import get_record_dict
from trouver_une_fresque_scraper.utils.date_and_time import get_dates
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

DEFAULT_TIMEOUT = 10000  # milliseconds


def extract_event_uuid(url: str) -> str | None:
    """Extract the event UUID from an Eventbrite URL."""
    match = re.search(r"/e/([^/?]+)", url)
    return match.group(1) if match else None


@contextmanager
def managed_browser(headless=False):
    """Context manager for Playwright browser."""
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


def delete_cookies_overlay(page: Page):
    """Remove cookie consent overlay if present."""
    try:
        # Wait a bit for the overlay to appear
        page.wait_for_timeout(1000)

        # The cookie consent is in a shadow DOM
        # Use evaluate to handle shadow DOM reliably
        clicked = page.evaluate(
            """
            () => {
                const manager = document.querySelector('#transcend-consent-manager');
                if (manager && manager.shadowRoot) {
                    const buttons = manager.shadowRoot.querySelectorAll('button');
                    for (const button of buttons) {
                        const text = button.textContent || '';
                        if (text.includes('Tout rejeter') || text.includes('Reject all')) {
                            button.click();
                            return true;
                        }
                    }
                }
                return false;
            }
        """
        )

        if clicked:
            logging.debug("Cookie consent rejected")
            page.wait_for_timeout(500)
        else:
            logging.debug("Cookie consent overlay not found or already dismissed")
    except Exception as e:
        logging.debug(f"Cookie consent overlay couldn't be handled: {e}")


def scroll_to_bottom(page: Page):
    """
    Scroll to bottom of page, clicking 'Show More' buttons.

    Continues scrolling and clicking until no more content can be loaded.
    """
    more_content = True
    consecutive_failures = 0
    max_failures = 3

    while more_content and consecutive_failures < max_failures:
        logging.info("Scrolling to the bottom...")
        try:
            # Scroll down
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

            # Wait for any dynamic content to load
            page.wait_for_timeout(1000)

            # Try to click the next button
            next_button = page.locator(
                "div.organizer-profile__section--content div.organizer-profile__show-more > button"
            ).first
            if next_button.is_visible(timeout=2000):
                next_button.scroll_into_view_if_needed(timeout=5000)
                next_button.click()
                consecutive_failures = 0  # Reset on success
                # Wait after clicking to let content load
                page.wait_for_timeout(1500)
            else:
                more_content = False
                logging.debug("Reached end of content - no more buttons")

        except PlaywrightTimeoutError:
            consecutive_failures += 1
            logging.debug(
                f"Timeout during scrolling (attempt {consecutive_failures}/{max_failures})"
            )
        except Exception as e:
            consecutive_failures += 1
            logging.warning(
                f"Error during scrolling (attempt {consecutive_failures}/{max_failures}): {e}"
            )

    if consecutive_failures >= max_failures:
        logging.debug("Stopped scrolling after max failures reached")


# ==================== Main Entry Point ====================


def get_eventbrite_data(sources, service=None, options=None):
    """
    Scrape EventBrite events using Playwright.

    Args:
        sources: List of source page configurations (dicts with 'id' and 'url')
        service: Unused (kept for compatibility)
        options: Unused (kept for compatibility)

    Returns:
        List of event records
    """
    logging.info("Scraping data from eventbrite.fr")

    headless = False
    if options and hasattr(options, "arguments") and len(options.arguments) > 0:
        headless = "-headless" in options.arguments

    with managed_browser(headless=headless) as browser:
        context = browser.new_context(locale='en-US')
        page = context.new_page()
        records = []

        for source in sources:
            try:
                logging.info(f"==================\nProcessing page {source}")
                page.goto(source["url"], wait_until="domcontentloaded")

                delete_cookies_overlay(page)

                # Scroll to bottom to load all events
                scroll_to_bottom(page)
                page.evaluate("window.scrollTo(0, 0)")

                # Wait for future events container
                # page.wait_for_selector('div[data-testid="organizer-profile__future-events"]', timeout=DEFAULT_TIMEOUT)

                # Extract links
                event_cards = page.locator("div.event-card").all()
                logging.info(f"Found {len(event_cards)} events")

                links = []
                for card in event_cards:
                    link_elements = card.locator("a.event-card-link").all()
                    for link_el in link_elements:
                        href = link_el.get_attribute("href")
                        if href:
                            links.append(href)

                links = np.unique(links)

                # Process each event
                for link in links:
                    event_records = process_event_page(page, link, source)
                    records.extend(event_records)

            except Exception as e:
                logging.error(
                    f"Failed to process organizer page {source.get('url', source)}: {e}",
                    exc_info=True,
                )
                raise

        context.close()

    return records


def process_event_page(page: Page, link: str, source: dict):
    """
    Process a single event page.

    Args:
        page: Playwright Page instance
        link: URL of the event page
        source: Source page configuration dict

    Returns:
        List of event records (can be multiple for events with multiple dates)
    """
    logging.info(f"\n-> Processing {link} ...")
    records = []

    try:
        page.goto(link, wait_until="domcontentloaded")
        delete_cookies_overlay(page)

        ################################################################
        # Has it expired?
        ################################################################
        expired_badge = page.locator('div[data-testid="enhancedExpiredEventsBadge"]').first
        try:
            if expired_badge.is_visible(timeout=1000):
                # If the element has children, it is enabled
                children = expired_badge.locator("*").count()
                if children > 0:
                    logging.info("Rejecting record: event expired")
                    return records
        except Exception:
            pass

        # Check alternative expired badge
        alt_expired_badge = page.locator("div.enhanced-expired-badge").first
        try:
            if alt_expired_badge.is_visible(timeout=1000):
                logging.info("Rejecting record: event expired")
                return records
        except Exception:
            pass

        ################################################################
        # Is it full?
        ################################################################
        sold_out = False
        sold_out_badge = page.locator('div[data-testid="salesEndedMessage"]').first
        try:
            if sold_out_badge.is_visible(timeout=1000):
                children_count = sold_out_badge.locator("*").count()
                sold_out = children_count > 0
        except Exception:
            pass

        if sold_out:
            # We reject sold out events as the Eventbrite UX hides
            # relevant info in this case (which looks like an awful practice)
            logging.info("Rejecting record: sold out")
            return records

        ################################################################
        # Parse event title
        ################################################################
        title_el = page.locator("h1").first
        title = title_el.text_content()

        if is_plenary(title):
            logging.info("Rejecting record: plénière")
            return records

        ###########################################################
        # Is it an online event?
        ################################################################
        online = is_online(title)
        if not online:
            short_location_el = page.locator("span.start-date-and-location__location").first
            try:
                if short_location_el.is_visible(timeout=1000):
                    online = is_online(short_location_el.text_content())
            except Exception:
                pass

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
            # Try multiple location selectors (Eventbrite uses different layouts)
            location_selectors = [
                'div[class^="Location-module__addressWrapper___"]',
                'address[class^="Address_address__"]',
            ]

            full_location = ""
            for selector in location_selectors:
                location_el = page.locator(selector).first
                try:
                    location_el.wait_for(state="visible", timeout=5000)
                    # Get inner text which preserves newlines for stacked elements
                    full_location = location_el.inner_text()
                    break
                except Exception:
                    continue

            if not full_location:
                logging.error(f"Location element not found for offline event {link}.")
                return records

            # Replace newlines with commas (stacked elements), then normalize spaces
            full_location = full_location.replace("\n", ", ")
            # Remove multiple spaces but keep the commas
            full_location = " ".join(full_location.split())
            # Remove empty parts (e.g., ", , " -> ", ")
            full_location = re.sub(r",\s*,", ",", full_location)
            # Remove leading/trailing commas and spaces
            full_location = full_location.strip(", ")

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
        description_selectors = [
            "div.event-description",
            'div[class^="Overview_summary__"]',
        ]

        description = ""
        for selector in description_selectors:
            description_el = page.locator(selector).first
            try:
                description_el.wait_for(state="visible", timeout=5000)
                description = description_el.text_content()
                if description:
                    break
            except Exception:
                continue

        if not description:
            logging.info("Rejecting record: Description not found.")
            return records

        ################################################################
        # Training?
        ################################################################
        training = is_training(title)

        ################################################################
        # Is it suited for kids?
        ################################################################
        kids = False

        event_info = []

        ################################################################
        # Single event with multiple dates (a "collection").
        ################################################################
        check_availability_btn = page.locator("button[id^='check-availability-btn-']").first

        try:
            has_collection_button = check_availability_btn.is_visible(timeout=1000)
        except Exception:
            has_collection_button = False

        if has_collection_button:
            # Click the button to open the modal
            try:
                logging.info("Found EventBrite collection, clicking availability button...")
                check_availability_btn.click()

                # Wait for modal to load using Playwright's native waiting
                logging.debug("Waiting for modal to load...")

                # Check for iframe first
                iframe_locator = page.frame_locator(
                    'iframe[id*="eventbrite-widget"], iframe[class*="modal"], iframe[title*="availability"]'
                ).first
                modal_page = None
                try:
                    # Try to access iframe content
                    test_element = iframe_locator.locator("body").first
                    test_element.wait_for(state="attached", timeout=2000)
                    modal_page = iframe_locator
                    logging.debug("Switching to iframe for modal content...")
                except Exception:
                    # No iframe, use main page
                    modal_page = page

                ################################################################
                # Wait for modal content to load using Playwright's native waiting
                ################################################################
                MODAL_TIMEOUT = 15000  # 15 seconds total timeout for modal content

                # Create locators for both modal types
                date_wrapper_locator = modal_page.locator('p[class*="dateWrapper"]')
                calendar_card_locator = modal_page.locator(
                    'div[class*="CompactCalendar"] div[class*="compactChoiceCardContainer"]'
                )

                # Wait for either type of content to appear
                try:
                    # Use first() to wait for at least one element of either type
                    modal_page.locator(
                        'p[class*="dateWrapper"], '
                        'div[class*="CompactCalendar"] div[class*="compactChoiceCardContainer"]'
                    ).first.wait_for(state="visible", timeout=MODAL_TIMEOUT)
                    logging.debug("Modal content is now visible")
                except PlaywrightTimeoutError:
                    logging.warning(
                        f"Modal content did not load within {MODAL_TIMEOUT}ms for {link}"
                    )

                # Now get all elements
                date_wrappers = date_wrapper_locator.all()
                calendar_date_cards = calendar_card_locator.all()

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
                            # Extract date information from the card
                            weekday_el = date_card.locator('p[class*="weekday"]').first
                            day_num_el = date_card.locator('p[class*="dateText"]').first
                            time_slot_el = date_card.locator('p[class*="timeSlot"]').first

                            weekday = weekday_el.text_content()  # e.g., "SAT"
                            day_num = day_num_el.text_content()  # e.g., "24"
                            time_slot = time_slot_el.text_content()  # e.g., "9:00 am"

                            # Get the month from the parent structure
                            month = "Unknown"
                            try:
                                # Try to find month header in the parent structure
                                month_header = modal_page.locator('p[class*="monthName"]').first
                                month = month_header.text_content()  # e.g., "January"
                            except Exception as e:
                                logging.debug(f"Could not find month header: {e}")

                            logging.debug(
                                f"Processing calendar date: {weekday}, {month} {day_num} at {time_slot}"
                            )

                            # Format the date string for parsing
                            date_str = f"{weekday}, {month} {day_num} {time_slot}"

                            try:
                                event_start_datetime, event_end_datetime = get_dates(date_str)
                            except FreskDateBadFormat as error:
                                logging.warning(
                                    f"Failed to parse calendar date '{date_str}': {error}"
                                )
                                continue

                            # Generate UUID
                            base_uuid = extract_event_uuid(link)
                            if not base_uuid:
                                logging.warning(f"Could not extract UUID from {link}")
                                continue
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
                            date_text = date_wrapper.text_content()
                            logging.debug(f"Processing date: {date_text}")

                            # Click on the date wrapper's parent card to reveal time slots
                            try:
                                clickable_parent = date_wrapper.locator(
                                    'xpath=ancestor::div[contains(@class, "EventInfoCard")]'
                                ).first
                                clickable_parent.click()
                                logging.debug(f"Clicked on date card for: {date_text}")

                                # Wait for time slots to load
                                logging.debug("Waiting for time slots to load...")
                                time_slot_list = modal_page.locator(
                                    'ul[class*="TimeSlotList"]'
                                ).first
                                try:
                                    time_slot_list.wait_for(
                                        state="visible", timeout=DEFAULT_TIMEOUT
                                    )
                                except Exception:
                                    logging.warning(
                                        f"Time slot list did not load for date: {date_text}"
                                    )
                                    continue

                                # Wait for time slot content to stabilize
                                page.wait_for_timeout(500)

                            except Exception as e:
                                logging.debug(f"Could not click date card: {e}")

                            # Find all time slots
                            all_time_slot_lists = modal_page.locator(
                                'ul[class*="TimeSlotList"]'
                            ).all()

                            if not all_time_slot_lists:
                                logging.warning(
                                    f"No time slot lists found for date: {date_text}"
                                )
                                continue

                            logging.debug(
                                f"Found {len(all_time_slot_lists)} time slot lists in modal"
                            )

                            # Extract time slot data
                            time_slots_data = []
                            for time_slot_list in all_time_slot_lists:
                                time_slot_lis = time_slot_list.locator("li").all()
                                for time_slot_li in time_slot_lis:
                                    try:
                                        time_element = time_slot_li.locator(
                                            'p[class*="sessionText"]'
                                        ).first
                                        time_text = time_element.text_content()
                                        if time_text:
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
                                    combined_text = f"{date_text} {time_text}"

                                    try:
                                        event_start_datetime, event_end_datetime = get_dates(
                                            combined_text
                                        )
                                    except FreskDateBadFormat as error:
                                        logging.warning(
                                            f"Failed to parse date '{combined_text}': {error}"
                                        )
                                        continue

                                    # Generate a unique UUID for this specific date/time combo
                                    base_uuid = extract_event_uuid(link)
                                    if not base_uuid:
                                        logging.warning(f"Could not extract UUID from {link}")
                                        continue
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
                    return records

            except Exception as e:
                logging.error(
                    f"Failed to process EventBrite collection for {link}: {e}", exc_info=True
                )
                return records
        else:
            # Regular single event
            ################################################################
            # Dates
            ################################################################
            date_selectors = [
                "time.start-date-and-location__date",
                '[data-testid="event-datetime"]',
            ]

            date_text = ""
            for selector in date_selectors:
                date_info_el = page.locator(selector).first
                try:
                    date_info_el.wait_for(state="visible", timeout=5000)
                    date_text = date_info_el.text_content()
                    if date_text:
                        break
                except Exception:
                    continue

            if not date_text:
                logging.info("Rejecting record: Date not found.")
                return records

            try:
                event_start_datetime, event_end_datetime = get_dates(date_text)
            except FreskDateBadFormat as error:
                logging.info(f"Reject record: {error}")
                return records

            ################################################################
            # Parse tickets link
            ################################################################
            tickets_link = page.url

            ################################################################
            # Parse event id
            ################################################################
            uuid = extract_event_uuid(tickets_link)
            if not uuid:
                logging.warning(f"Could not extract UUID from {tickets_link}")
                return records

            event_info.append([uuid, event_start_datetime, event_end_datetime, tickets_link])

        ################################################################
        # Session loop
        ################################################################
        for index, (
            uuid,
            event_start_datetime,
            event_end_datetime,
            event_link,
        ) in enumerate(event_info):
            record = get_record_dict(
                f"{source['id']}-{uuid}",
                source["id"],
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
                source.get(
                    "language_code",
                    detect_language_code(title, description),
                ),
                online,
                training,
                sold_out,
                kids,
                event_link,
                event_link,
                description,
            )
            records.append(record)
            logging.info(f"Successfully scraped {event_link}\n{json.dumps(record, indent=4)}")

    except (FreskDateBadFormat, FreskError) as e:
        # Known business logic exceptions that should skip this event
        logging.info(f"Skipping event {link}: {e}")
        return records
    except Exception as e:
        logging.error(f"Unexpected error processing event page {link}: {e}", exc_info=True)
        raise

    return records
