import json
import logging

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from trouver_une_fresque_scraper.db.records import get_record_dict
from trouver_une_fresque_scraper.utils.browser import managed_browser, DEFAULT_TIMEOUT
from trouver_une_fresque_scraper.utils.date_and_time import get_dates
from trouver_une_fresque_scraper.utils.errors import (
    FreskError,
    FreskDateBadFormat,
)
from trouver_une_fresque_scraper.utils.keywords import (
    is_canceled,
    is_online,
    is_training,
)
from trouver_une_fresque_scraper.utils.language import detect_language_code
from trouver_une_fresque_scraper.utils.location import get_address


def collect_event_links(page: Page, source: dict) -> list[str]:
    """
    Collect all event links from a Glide listing page.

    Clicks the filter tab, then iterates through all collection items
    across pagination pages, collecting event URLs.
    """
    all_links = []

    # Click the filter tab button
    tab_button = page.locator(f"div.button-text:has-text('{source['filter']}')")
    tab_button.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    tab_button.click()
    page.wait_for_timeout(5000)

    while True:
        # Wait for collection items to appear
        items = page.locator("div.collection-item[role='button']")
        try:
            items.first.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        except PlaywrightTimeoutError:
            logging.warning(f"No collection items found for {source['url']}")
            break

        item_count = items.count()
        logging.info(f"Found {item_count} elements on current page")

        for i in range(item_count):
            # Re-query items each iteration (DOM may have changed after back navigation)
            items = page.locator("div.collection-item[role='button']")

            # Wait until the expected number of items is loaded again
            max_tries = 10
            for attempt in range(max_tries):
                if items.count() == item_count:
                    break
                page.reload()
                page.wait_for_timeout(5000)
                items = page.locator("div.collection-item[role='button']")
            else:
                raise RuntimeError(
                    f"Cannot load the {item_count} JS elements after {max_tries} tries."
                )

            items.nth(i).click()
            page.wait_for_timeout(5000)

            link = page.url
            all_links.append(link)
            logging.info(f"Collected link: {link}")

            page.go_back()
            page.wait_for_timeout(5000)

        # Try clicking the "Next" pagination button
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            next_button = page.locator("button[aria-label='Next']")
            if next_button.is_visible(timeout=DEFAULT_TIMEOUT):
                next_button.scroll_into_view_if_needed()
                page.wait_for_timeout(2000)
                next_button.click()
                page.wait_for_timeout(2000)
            else:
                break
        except PlaywrightTimeoutError:
            break

    logging.info(f"Total links collected: {len(all_links)}")
    return all_links


# ==================== Main Entry Point ====================


def get_glide_data(sources, service=None, options=None):
    """
    Scrape Glide events using Playwright.

    Args:
        sources: List of source page configurations (dicts with 'id', 'url', 'filter')
        service: Unused (kept for compatibility)
        options: Unused (kept for compatibility)

    Returns:
        List of event records
    """
    logging.info("Scraping data from glide.page")

    headless = False
    if options and hasattr(options, "arguments") and len(options.arguments) > 0:
        headless = "-headless" in options.arguments

    with managed_browser(headless=headless) as browser:
        context = browser.new_context()
        page = context.new_page()
        records = []

        for source in sources:
            try:
                logging.info(f"==================\nProcessing page {source}")
                page.goto(source["url"], wait_until="domcontentloaded")
                page.wait_for_timeout(20000)

                # Phase 1: Collect all event links across pagination pages
                links = collect_event_links(page, source)

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
    Process a single Glide event page.

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
        page.wait_for_timeout(5000)

        ################################################################
        # Is it canceled?
        ################################################################
        large_title_el = page.locator("h2.headlineMedium").first
        try:
            if large_title_el.is_visible(timeout=3000):
                large_title = large_title_el.text_content()
                if is_canceled(large_title):
                    logging.info("Rejecting record: canceled")
                    return None
        except PlaywrightTimeoutError:
            pass

        ################################################################
        # Parse event id
        ################################################################
        uuid = link.split("/")[-1]
        if not uuid:
            logging.info("Rejecting record: UUID not found")
            return None

        ################################################################
        # Parse event title
        ################################################################
        title_el = page.locator("h2.headlineSmall").first
        title_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        title = title_el.text_content()

        ################################################################
        # Parse start and end dates
        ################################################################
        date_label_el = page.locator("li div:has-text('Date')").first
        date_label_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        parent_el = date_label_el.locator("xpath=..")
        event_time_el = parent_el.locator("> *:nth-child(2)")
        event_time = event_time_el.text_content().lower()

        try:
            event_start_datetime, event_end_datetime = get_dates(event_time)
        except FreskDateBadFormat as error:
            logging.info(f"Rejecting record: {error}")
            return None

        ################################################################
        # Is it an online event?
        ################################################################
        format_label_el = page.locator("li div:has-text('Format')").first
        format_label_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        parent_el = format_label_el.locator("xpath=..")
        online_el = parent_el.locator("> *:nth-child(2)")
        online = is_online(online_el.text_content())

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
            try:
                address_label_el = page.locator("li div:has-text('Adresse')").first
                address_label_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
                parent_el = address_label_el.locator("xpath=..")
                address_el = parent_el.locator("> *:nth-child(2)")
                full_location = address_el.text_content()
            except PlaywrightTimeoutError:
                logging.info("Rejecting record: empty address")
                return None

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
                return None

        ################################################################
        # Description
        ################################################################
        description_label_el = page.locator("li div:has-text('Description')").first
        description_label_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        parent_el = description_label_el.locator("xpath=..")
        description_el = parent_el.locator("> *:nth-child(2)")
        description = description_el.text_content()

        ################################################################
        # Training?
        ################################################################
        training = is_training(title)

        ################################################################
        # Is it full?
        ################################################################
        attendees_label_el = page.locator("li div:has-text('participant')").first
        attendees_label_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        parent_el = attendees_label_el.locator("xpath=..")
        attendees_el = parent_el.locator("> *:nth-child(2)")
        attendees = attendees_el.text_content()

        parts = attendees.split("/")
        sold_out = len(parts) == 2 and parts[0].strip() == parts[1].strip()

        ################################################################
        # Is it suited for kids?
        ################################################################
        kids = False

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
            source.get(
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

        logging.info(f"Successfully scraped {link}\n{json.dumps(record, indent=4)}")
        return record

    except (FreskDateBadFormat, FreskError) as e:
        logging.info(f"Skipping event {link}: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error processing event page {link}: {e}", exc_info=True)
        raise
