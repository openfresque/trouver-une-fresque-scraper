import json
import re
import logging

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from trouver_une_fresque_scraper.db.records import get_record_dict
from trouver_une_fresque_scraper.utils.browser import managed_browser, DEFAULT_TIMEOUT
from trouver_une_fresque_scraper.utils.date_and_time import get_dates
from trouver_une_fresque_scraper.utils.errors import (
    FreskError,
    FreskDateBadFormat,
    FreskLanguageNotRecognized,
)
from trouver_une_fresque_scraper.utils.keywords import (
    is_training,
    is_sold_out,
    is_for_kids,
)
from trouver_une_fresque_scraper.utils.language import get_language_code
from trouver_une_fresque_scraper.utils.location import get_address


def extract_event_uuid(link: str) -> str | None:
    """Extract the first UUID from an FDC event URL."""
    uuid_pattern = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    uuids = re.findall(uuid_pattern, link)
    return uuids[0] if uuids else None


def collect_links_from_iframe(page: Page, source: dict) -> list[str]:
    """
    Collect all event links from the listing page, handling pagination.

    Navigates the iframe's pagination to gather links across all pages,
    without ever leaving the listing page.
    """
    all_links = []

    while True:
        iframe = page.frame_locator("iframe")

        # Wait for iframe content to load
        try:
            iframe.locator("a.link-dark").first.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        except PlaywrightTimeoutError:
            logging.warning(f"No events found in iframe for {source['url']}")
            break

        link_elements = iframe.locator("a.link-dark").all()
        for el in link_elements:
            # Use evaluate to get the resolved absolute URL (get_attribute
            # returns the raw relative path, which page.goto() can't handle)
            href = el.evaluate("node => node.href")
            if href:
                all_links.append(href)

        logging.info(f"Collected {len(link_elements)} links from current page")

        # Try clicking "Suivant" for pagination
        try:
            next_button = iframe.locator("a.page-link:has-text('Suivant')")
            if next_button.is_visible(timeout=2000):
                next_button.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                next_button.click()
                page.wait_for_timeout(5000)
            else:
                break
        except PlaywrightTimeoutError:
            break

    logging.info(f"Total links collected: {len(all_links)}")
    return all_links


# ==================== Main Entry Point ====================


def get_fdc_data(sources, service=None, options=None):
    """
    Scrape FDC (Fresque du Climat) events using Playwright.

    Args:
        sources: List of source page configurations (dicts with 'id' and 'url')
        service: Unused (kept for compatibility)
        options: Unused (kept for compatibility)

    Returns:
        List of event records
    """
    logging.info("Scraping data from fresqueduclimat.org")

    headless = False
    if options and hasattr(options, "arguments") and len(options.arguments) > 0:
        headless = "-headless" in options.arguments

    with managed_browser(headless=headless) as browser:
        context = browser.new_context()
        page = context.new_page()
        records = []

        for source in sources:
            try:
                logging.info(f"========================\nProcessing source {source}")
                page.goto(source["url"], wait_until="domcontentloaded")

                # Phase 1: Collect all event links across pagination pages
                links = collect_links_from_iframe(page, source)

                # Phase 2: Process each event page
                for link in links:
                    event_record = process_event_page(page, link, source)
                    if event_record:
                        records.append(event_record)

            except Exception as e:
                logging.error(
                    f"Failed to process source page {source.get('url', source)}: {e}",
                    exc_info=True,
                )
                raise

        context.close()

    return records


def process_event_page(page: Page, link: str, source: dict) -> dict | None:
    """
    Process a single FDC event page.

    Args:
        page: Playwright Page instance
        link: URL of the event page
        source: Source page configuration dict

    Returns:
        Event record dict, or None if the event should be skipped
    """
    logging.info(f"\n-> Processing {link} ...")

    try:
        page.goto(link, wait_until="domcontentloaded")

        ################################################################
        # Parse event id
        ################################################################
        uuid = extract_event_uuid(link)
        if not uuid:
            logging.info("Rejecting record: UUID not found")
            return None

        ################################################################
        # Parse event title
        ################################################################
        title_el = page.locator("h3").first
        title_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        title = title_el.inner_text()

        ################################################################
        # Parse start and end dates
        ################################################################
        clock_icon = page.locator(".fa-clock").first
        clock_icon.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        parent_div = clock_icon.locator("xpath=..")
        event_time = parent_div.inner_text().strip()

        try:
            event_start_datetime, event_end_datetime = get_dates(event_time)
        except FreskDateBadFormat as error:
            logging.info(f"Reject record: {error}")
            return None

        ################################################################
        # Workshop language
        ################################################################
        language_code = None
        try:
            globe_icon = page.locator("div.mb-3 > i.fa-globe").first
            globe_icon.wait_for(state="visible", timeout=2000)
            parent = globe_icon.locator("xpath=..")
            language_code = get_language_code(parent.inner_text())
        except FreskLanguageNotRecognized as e:
            logging.warning(f"Unable to parse workshop language: {e}")
            language_code = None
        except (PlaywrightTimeoutError, Exception):
            logging.warning("Unable to find workshop language on the page.")
            language_code = None

        ################################################################
        # Is it an online event?
        ################################################################
        online = page.locator(".fa-video").count() > 0

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
            pin_icon = page.locator(".fa-map-pin").first
            pin_icon.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
            parent_div = pin_icon.locator("xpath=..")
            full_location = parent_div.inner_text()

            try:
                logging.info(f"Full location: {full_location}")
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
                return None

        ################################################################
        # Description
        ################################################################
        description_title_el = page.locator("strong:has-text('Description')").first
        description_title_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        parent_description_el = description_title_el.locator("xpath=..")
        description = parent_description_el.inner_text()

        ################################################################
        # Training?
        ################################################################
        training = is_training(title)

        ################################################################
        # Is it full?
        ################################################################
        user_icon = page.locator(".fa-user").first
        user_icon.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        parent_container = user_icon.locator("xpath=../..")
        sold_out = is_sold_out(parent_container.inner_text())

        ################################################################
        # Is it suited for kids?
        ################################################################
        kids = is_for_kids(description) and not training

        ################################################################
        # Parse tickets link
        ################################################################
        user_icon_link = page.locator(".fa-user").first
        parent_link = user_icon_link.locator("xpath=..")
        tickets_link = parent_link.evaluate("node => node.href")

        ################################################################
        # Building final object
        ################################################################
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
            language_code,
            online,
            training,
            sold_out,
            kids,
            link,
            tickets_link,
            description,
        )

        logging.info(f"Successfully scraped {link}\n{json.dumps(record, indent=4)}")
        return record

    except (FreskDateBadFormat, FreskError) as e:
        logging.info(f"Skipping event {link}: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error processing event page {link}: {e}", exc_info=True)
        raise
