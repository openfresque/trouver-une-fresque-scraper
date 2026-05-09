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
    is_online,
    is_training,
    is_for_kids,
)
from trouver_une_fresque_scraper.utils.language import detect_language_code
from trouver_une_fresque_scraper.utils.location import get_address


def dismiss_cookie_modal(page: Page):
    """Dismiss the Axeptio cookie consent modal if present."""
    try:
        reject_button = page.locator("#axeptio_btn_dismiss")
        reject_button.wait_for(state="visible", timeout=5000)
        reject_button.click()
        logging.info("Cookie consent modal dismissed")
        page.wait_for_timeout(1000)
    except PlaywrightTimeoutError:
        logging.debug("Cookie consent modal not found or already dismissed")
    except Exception as e:
        logging.debug(f"Cookie consent modal couldn't be handled: {e}")


def scroll_to_bottom(page: Page):
    """
    Scroll to bottom of page, clicking 'Load More' buttons.

    Continues scrolling and clicking until no more content can be loaded.
    """
    while True:
        logging.info("Scrolling to the bottom...")
        try:
            page.wait_for_timeout(2000)

            next_button = page.locator('button[data-hook="load-more-button"]')
            next_button.wait_for(state="visible", timeout=10000)

            next_button.scroll_into_view_if_needed()
            page.wait_for_timeout(2000)
            next_button.click()
        except PlaywrightTimeoutError:
            break


def collect_event_links(page: Page) -> list[str]:
    """
    Collect all event links from the organization page.

    Scrolls down to load all events, clicks the "show all" button if
    present, then extracts all event links.
    """
    # Try clicking the "show all actions" button if present
    show_all_button = page.locator(
        'button[data-ux="Explore_OrganizationPublicPage_Actions_ActionEvent_ShowAllActions"]'
    )
    try:
        if show_all_button.is_visible(timeout=2000):
            show_all_button.click()
    except Exception:
        pass

    link_elements = page.locator("a.ActionLink-Event").all()
    links = []
    for el in link_elements:
        href = el.get_attribute("href")
        if href:
            links.append(href)

    logging.info(f"Found {len(links)} events")
    return links


# ==================== Main Entry Point ====================


def get_helloasso_data(sources, service=None, options=None):
    """
    Scrape HelloAsso events using Playwright.

    Args:
        sources: List of source page configurations (dicts with 'id' and 'url')
        service: Unused (kept for compatibility)
        options: Unused (kept for compatibility)

    Returns:
        List of event records
    """
    logging.info("Scraping data from helloasso.com")

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
                page.wait_for_timeout(3000)

                # Dismiss cookie consent modal if present
                dismiss_cookie_modal(page)

                # Collect all event links from the listing page
                links = collect_event_links(page)

                # Process each event page
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
    Process a single HelloAsso event page.

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
        uuid = link.split("/")[-1]
        if not uuid:
            logging.info("Rejecting record: UUID not found")
            return None

        ################################################################
        # Parse event title
        ################################################################
        title_el = page.locator("h1").first
        title_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        title = title_el.text_content()

        ################################################################
        # Parse start and end dates
        ################################################################
        date_info_el = page.locator("span.CampaignHeader--Date").first
        try:
            date_info_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        except PlaywrightTimeoutError:
            logging.info("Rejecting record: date not found")
            return None

        event_time = date_info_el.text_content().strip()

        try:
            event_start_datetime, event_end_datetime = get_dates(event_time)
        except FreskDateBadFormat as error:
            logging.info(f"Rejecting record: {error}")
            return None

        ################################################################
        # Is it an online event?
        ################################################################
        online = is_online(title)

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
            location_el = page.locator("section.CardAddress--Location").first
            try:
                location_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
            except PlaywrightTimeoutError:
                logging.info("Rejecting record: no location")
                return None

            full_location = location_el.text_content()

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
        description_el = page.locator("div.CampaignHeader--Description").first
        try:
            description_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        except PlaywrightTimeoutError:
            logging.info("Rejecting record: no description")
            return None

        description = description_el.text_content()

        ################################################################
        # Training?
        ################################################################
        training = is_training(title)

        ################################################################
        # Is it full?
        ################################################################
        sold_out = False

        ################################################################
        # Is it suited for kids?
        ################################################################
        kids = is_for_kids(title)

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
