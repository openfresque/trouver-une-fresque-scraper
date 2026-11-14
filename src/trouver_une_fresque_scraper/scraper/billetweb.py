import json
import logging
import re

from datetime import timedelta

from playwright.sync_api import FrameLocator, Page, TimeoutError as PlaywrightTimeoutError

from trouver_une_fresque_scraper.db.records import get_record_dict
from trouver_une_fresque_scraper.utils.browser import managed_browser, DEFAULT_TIMEOUT
from trouver_une_fresque_scraper.utils.date_and_time import get_dates
from trouver_une_fresque_scraper.utils.errors import FreskError
from trouver_une_fresque_scraper.utils.keywords import (
    has_external_tickets,
    is_for_kids,
    is_gift_card,
    is_online,
    is_training,
)
from trouver_une_fresque_scraper.utils.language import detect_language_code
from trouver_une_fresque_scraper.utils.location import get_address

# Context title of a session page: "session title : date and time\nlocation".
# The title part and the location part are optional.
CONTEXT_TITLE_PATTERN = r"\s*((?P<title>.*) : )?(?P<event_time>.*)(\n\s*(?P<full_location>.*))?"


# ==================== Main Entry Point ====================


def get_billetweb_data(sources, headless=False):
    """
    Scrape Billetweb events using Playwright.

    Args:
        sources: List of source page configurations (dicts with 'id', 'url' and 'iframe')
        headless: Run the browser in headless mode

    Returns:
        List of event records
    """
    logging.info("Scraping data from www.billetweb.fr")

    with managed_browser(headless=headless) as browser:
        # Billetweb renders the event dates client-side in the navigator
        # language, and get_dates() only parses the English date format.
        # Force the "en-US" locale, like the previous Selenium setup did
        # with the "en-us" accept language.
        context = browser.new_context(locale="en-US")
        page = context.new_page()
        records = []

        for source in sources:
            try:
                logging.info(f"==================\nProcessing page {source}")

                # Phase 1: Collect all event links from the listing page
                links = collect_event_links(page, source)

                # Phase 2: Process each event page
                for link in links:
                    records.extend(process_event_page(page, link, source))

            except Exception as e:
                logging.error(
                    f"Failed to process source page {source.get('url', source)}: {e}",
                    exc_info=True,
                )
                raise

        context.close()

    return records


def collect_event_links(page: Page, source: dict) -> list[str]:
    """
    Collect all event links from the listing page.

    The listing page embeds the event list in an iframe whose id is defined
    in the source configuration.

    Args:
        page: Playwright Page instance
        source: Source page configuration dict

    Returns:
        List of event page URLs
    """
    page.goto(source["url"], wait_until="domcontentloaded")

    frame = page.frame_locator(f"#{source['iframe']}")
    try:
        frame.locator("body").first.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)
    except PlaywrightTimeoutError:
        logging.info("Rejecting record: iframe not found")
        return []

    try:
        frame.locator("a.naviguate").first.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    except PlaywrightTimeoutError:
        logging.info(f"No events found in iframe for {source['url']}")
        return []

    links = []
    for el in frame.locator("a.naviguate").all():
        # Use evaluate to get the resolved absolute URL (get_attribute
        # returns the raw relative path, which page.goto() can't handle)
        href = el.evaluate("node => node.href")
        if href:
            links.append(href)

    logging.info(f"Found {len(links)} events")
    return links


def process_event_page(page: Page, link: str, source: dict) -> list[dict]:
    """
    Process a single Billetweb event page and all of its sessions.

    Args:
        page: Playwright Page instance
        link: URL of the event page
        source: Source page configuration dict

    Returns:
        List of event records (one record per session for multi-time events)
    """
    logging.info(f"------------------\nProcessing event {link}")

    # Useful for different workshops sharing same event link
    if "filter" in source and source["filter"] not in link:
        logging.info("Rejecting filter: expected filter keyword not present in current link")
        return []

    page.goto(link, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    ################################################################
    # Description
    ################################################################
    description = get_event_description(page)
    if not description:
        return []

    ################################################################
    # Parse event id
    ################################################################
    event_id_match = re.search(r"/([^/]+?)&", link)
    if not event_id_match:
        logging.info("Rejecting record: event_id not found")
        return []
    event_id = event_id_match.group(1)

    ################################################################
    # Parse main title
    ################################################################
    main_title = get_event_title(page)

    ################################################################
    # Location data
    ################################################################
    main_full_location = get_event_location(page)

    # Retrieve sessions if exist
    shop = page.frame_locator("#shop_block iframe")
    session_links = collect_session_links(page, shop)

    event_info = []

    ################################################################
    # Multi-time management
    ################################################################
    for session_link in session_links:
        info = scrape_session(page, session_link, main_title, main_full_location, event_id)
        if info:
            event_info.append(info)

    ################################################################
    # Mono-time management
    ################################################################
    if not session_links:
        # Parse start and end dates
        start_time_el = page.locator("#event_title > div.event_start_time > span.text")
        if start_time_el.count():
            event_time = start_time_el.first.inner_text()
        else:
            start_time_el = page.locator(
                "#description_block > div.event_title > span > a > div.event_start_time"
            ).first
            start_time_el.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)
            event_time = start_time_el.inner_text()

        # Is it full?
        sold_out = is_sold_out(shop)

        event_info.append([main_title, event_time, main_full_location, sold_out, link, event_id])

    return build_records(event_info, source, link, description)


def get_event_description(page: Page) -> str:
    """
    Read the event description, expanding it first if needed.

    Returns the description text, or an empty string if the event must be
    rejected (no description or empty description).
    """
    # Click on "Read more" to expand the truncated description. The link is
    # present but hidden when the description is not truncated.
    more_info = page.locator("#more_info").first
    if more_info.is_visible():
        more_info.click()

    description_el = page.locator("#description").first
    try:
        description_el.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)
    except PlaywrightTimeoutError:
        logging.info("Rejecting record: no description")
        return ""

    description = description_el.inner_text().strip()
    if not description:
        logging.info("Rejecting record: empty description")

    return description


def get_event_title(page: Page) -> str:
    """Read the main event title."""
    title_el = page.locator("#event_title > div.event_name")
    if title_el.count():
        return title_el.first.inner_text().strip()

    title_el = page.locator("#description_block > div.event_title > div.event_name").first
    title_el.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)
    return title_el.inner_text().strip()


def get_event_location(page: Page) -> str:
    """Read the main event location, empty if not found."""
    try:
        location_el = page.locator("div.location_summary")
        if location_el.count():
            return location_el.first.inner_text().strip()

        location_el = page.locator(
            "#page_block_location > div.location > div.location_info > div.address > a"
        )
        if location_el.count():
            return location_el.first.inner_text().strip()
    except Exception:
        # The location is optional, scraping can continue without it
        pass

    return ""


def collect_session_links(page: Page, shop: FrameLocator) -> list[str]:
    """
    Collect the session links of an event from its shop iframe.

    Multi-time events list their sessions inside this iframe. When a
    multi-time event has only one date, the shop lands directly on the
    basket page: in that case, follow the back link to reach the session
    list. Mono-time events have no session links at all.

    Args:
        page: Playwright Page instance
        shop: FrameLocator of the shop iframe

    Returns:
        List of session page URLs (empty for mono-time events)
    """
    shop.locator("body").first.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)
    page.wait_for_timeout(2000)  # let the shop page render its content

    back_links = shop.locator(".back_header_link.summarizable")
    if back_links.count():
        # Case of Multi-time with only one date, we arrive directly to
        # Basket, so get back to sessions
        back_links.first.click()
        try:
            shop.locator("a.sesssion_href").first.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
        except PlaywrightTimeoutError:
            logging.warning("Session list not found after going back from the basket")

    session_links = []
    for el in shop.locator("a.sesssion_href").all():
        # Use evaluate to get the resolved absolute URL (get_attribute
        # returns the raw relative path, which page.goto() can't handle)
        href = el.evaluate("node => node.href")
        if href:
            session_links.append(href)

    return session_links


def scrape_session(
    page: Page,
    session_link: str,
    main_title: str,
    main_full_location: str,
    event_id: str,
) -> list | None:
    """
    Scrape a single session page of a multi-time event.

    Args:
        page: Playwright Page instance
        session_link: URL of the session page
        main_title: Title of the event, fallback for sessions without title
        main_full_location: Location of the event, fallback for sessions
            without location
        event_id: Id of the event

    Returns:
        A [title, event_time, full_location, sold_out, ticket_link, uuid]
        entry, or None if the session must be skipped
    """
    page.goto(session_link, wait_until="domcontentloaded")

    context_el = page.locator("#context_title").first
    context_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

    # Parse title, dates, location
    sub_title, event_time, sub_full_location = parse_session_context(
        context_el.inner_text(), main_title, main_full_location
    )

    # Is it full?
    sold_out = is_sold_out(page)

    # Parse session id
    session_id_match = re.search(r"&session=(\d+)", session_link)
    if not session_id_match:
        logging.info("Rejecting record: session id not found")
        return None

    uuid = f"{event_id}-{session_id_match.group(1)}"

    return [sub_title, event_time, sub_full_location, sold_out, session_link, uuid]


def parse_session_context(
    context: str, main_title: str, main_full_location: str
) -> tuple[str, str, str]:
    """
    Parse the title, date and location of a session from its context title.

    Args:
        context: Text of the #context_title element of the session page
        main_title: Title of the event, fallback for sessions without title
        main_full_location: Location of the event, fallback for sessions
            without location

    Returns:
        A (title, event_time, full_location) tuple
    """
    match = re.match(CONTEXT_TITLE_PATTERN, context)

    # Selenium's .text trimmed the element text, inner_text() does not:
    # strip the captured groups to keep the same behavior.
    title = (match.group("title") or "").strip()
    if not title:
        sub_title = main_title
    elif "atelier" in title.lower():
        sub_title = title
    else:
        sub_title = main_title + " - " + title

    event_time = match.group("event_time")
    full_location = (match.group("full_location") or "").strip()
    sub_full_location = full_location if full_location else main_full_location

    return sub_title, event_time, sub_full_location


def is_sold_out(container: Page | FrameLocator) -> bool:
    """
    Check whether an event is sold out.

    The presence of div.block indicates that the event is sold out, except
    when its text indicates that inscriptions are handled by an external
    website.

    Args:
        container: Page (session page) or FrameLocator (shop iframe) holding
            the div.block element
    """
    block = container.locator("div.block")
    if block.count():
        return not has_external_tickets(block.first.inner_text())
    return False


def build_records(event_info: list, source: dict, link: str, description: str) -> list[dict]:
    """
    Build the final records from the scraped session entries.

    Args:
        event_info: List of [title, event_time, full_location, sold_out,
            ticket_link, uuid] entries
        source: Source page configuration dict
        link: URL of the event page
        description: Description of the event

    Returns:
        List of event records
    """
    records = []

    ################################################################
    # Session loop
    ################################################################
    for index, (title, event_time, full_location, sold_out, ticket_link, uuid) in enumerate(
        event_info
    ):
        logging.info(f"\n-> Processing session {index+1}/{len(event_info)} {ticket_link} ...")
        if is_gift_card(title):
            logging.info("Rejecting record: gift card")
            continue

        ################################################################
        # Date and time
        ################################################################
        try:
            event_start_datetime, event_end_datetime = get_dates(event_time)
        except FreskError as e:
            logging.info(f"Rejecting record: {e}")
            continue

        if event_end_datetime - event_start_datetime > timedelta(days=1):
            logging.info(f"Rejecting record: event is too long: {event_time}")
            continue

        # Is it an online event?
        online = is_online(title) or is_online(full_location)
        # "Online event" is a button added by billetweb. Chromium renders it
        # with extra spaces, so strip the title after removing it.
        title = title.replace(" Online event", "").strip()

        ################################################################
        # Location data
        ################################################################
        location_name = (
            address
        ) = city = department = longitude = latitude = zip_code = country_code = ""
        if not online:
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
                continue

        # Training?
        training = is_training(title)

        # Is it suited for kids?
        kids = is_for_kids(title) and not training  # no trainings for kids

        # Building final object
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
            ticket_link,
            description,
        )
        records.append(record)
        logging.info(f"Successfully scraped:\n{json.dumps(record, indent=4)}")

    return records
