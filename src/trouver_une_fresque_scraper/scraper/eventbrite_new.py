import json
import logging
import re
import urllib.request
import urllib.error

from datetime import datetime, timedelta

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from trouver_une_fresque_scraper.db.records import get_record_dict
from trouver_une_fresque_scraper.utils.browser import managed_browser, DEFAULT_TIMEOUT
from trouver_une_fresque_scraper.utils.date_and_time import get_dates, DEFAULT_DURATION
from trouver_une_fresque_scraper.utils.errors import (
    FreskError,
    FreskDateBadFormat,
)
from trouver_une_fresque_scraper.utils.keywords import (
    is_plenary,
    is_online,
    is_training,
    is_for_kids,
)
from trouver_une_fresque_scraper.utils.language import detect_language_code
from trouver_une_fresque_scraper.utils.location import get_address


def extract_event_uuid(url: str) -> str | None:
    """Extract the event UUID from an Eventbrite URL (numeric ID at the end)."""
    match = re.search(r"-(\d+)(?:\?|$)", url)
    return match.group(1) if match else None


def delete_cookies_overlay(page: Page):
    """Remove Transcend cookie consent overlay if present (shadow DOM)."""
    try:
        page.wait_for_timeout(1000)
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


def collect_event_links(page: Page, source: dict) -> list[str]:
    """
    Collect all event links from the organizer profile page.

    Parses __NEXT_DATA__ for the first batch of events, then clicks the
    "Voir plus" / "See more" button to load additional events from the DOM.
    """
    all_links = []

    # Phase 1: Extract links from __NEXT_DATA__ JSON
    try:
        next_data_el = page.locator("script#__NEXT_DATA__")
        next_data_el.wait_for(state="attached", timeout=DEFAULT_TIMEOUT)
        raw_json = next_data_el.text_content()
        next_data = json.loads(raw_json)
        page_props = next_data.get("props", {}).get("pageProps", {})

        upcoming_events = page_props.get("upcomingEvents", [])
        has_more = page_props.get("hasMoreUpcoming", False)
        total_events = page_props.get("upcomingEventsTotal", 0)

        for event in upcoming_events:
            url = event.get("url")
            if url:
                all_links.append(url)

        logging.info(
            f"Extracted {len(all_links)} links from __NEXT_DATA__ "
            f"(total: {total_events}, has_more: {has_more})"
        )
    except Exception as e:
        logging.warning(f"Could not parse __NEXT_DATA__: {e}")
        has_more = False

    # Phase 2: Click "Voir plus" / "See more" to load remaining events
    if has_more:
        consecutive_failures = 0
        max_failures = 3

        while consecutive_failures < max_failures:
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)

                # The new template uses a ShowMoreButton wrapper
                show_more_button = page.locator(
                    'div[class*="ShowMoreButton"] button, '
                    'button:has-text("Voir plus"), '
                    'button:has-text("See more")'
                ).first

                if show_more_button.is_visible(timeout=3000):
                    show_more_button.scroll_into_view_if_needed()
                    page.wait_for_timeout(500)
                    show_more_button.click()
                    consecutive_failures = 0
                    page.wait_for_timeout(2000)
                else:
                    logging.debug("No more 'Show More' button visible")
                    break

            except PlaywrightTimeoutError:
                consecutive_failures += 1
                logging.debug(
                    f"Timeout clicking 'Show More' (attempt {consecutive_failures}/{max_failures})"
                )
            except Exception as e:
                consecutive_failures += 1
                logging.warning(
                    f"Error clicking 'Show More' (attempt {consecutive_failures}/{max_failures}): {e}"
                )

        # Collect newly loaded event links from the DOM
        # Use desktop grid cards to avoid duplicates (mobile grid has same cards)
        card_links = page.locator(
            'div[class*="EventsBucket_gridDesktopContent"] '
            'a[class*="EventCardLink_event-card-link"]'
        ).all()

        dom_links = set()
        for link_el in card_links:
            href = link_el.get_attribute("href")
            if href:
                # Eventbrite card links can be relative (e.g. /e/slug-12345)
                if href.startswith("/"):
                    # Construct absolute URL from the current page's origin
                    origin = page.evaluate("window.location.origin")
                    href = f"{origin}{href}"
                dom_links.add(href)

        # Merge with __NEXT_DATA__ links (deduplicate by event ID)
        existing_ids = set()
        for link in all_links:
            eid = extract_event_uuid(link)
            if eid:
                existing_ids.add(eid)

        for link in dom_links:
            eid = extract_event_uuid(link)
            if eid and eid not in existing_ids:
                # Strip tracking query params
                clean_link = link.split("?")[0]
                all_links.append(clean_link)
                existing_ids.add(eid)

    logging.info(f"Total links collected: {len(all_links)}")
    return all_links


# ==================== Main Entry Point ====================


def get_eventbrite_new_data(sources, service=None, options=None):
    """
    Scrape Eventbrite events using Playwright (new template).

    Args:
        sources: List of source page configurations (dicts with 'id' and 'url')
        service: Unused (kept for compatibility)
        options: Unused (kept for compatibility)

    Returns:
        List of event records
    """
    logging.info("Scraping data from eventbrite (new template)")

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

                delete_cookies_overlay(page)

                # Phase 1: Collect all event links
                links = collect_event_links(page, source)

                # Phase 2: Process each event page
                for link in links:
                    event_records = process_event_page(page, link, source)
                    records.extend(event_records)

            except Exception as e:
                logging.error(
                    f"Failed to process source page {source.get('url', source)}: {e}",
                    exc_info=True,
                )
                raise

        context.close()

    return records


def parse_iso_datetime(iso_str: str) -> datetime:
    """Parse an ISO 8601 local datetime string (e.g. '2026-05-19T09:15:00')."""
    return datetime.fromisoformat(iso_str)


def process_event_page(page: Page, link: str, source: dict) -> list[dict]:
    """
    Process a single Eventbrite event page (new template).

    Uses DOM selectors with data-testid attributes for stability.
    Falls back to __NEXT_DATA__ JSON for structured data when needed.

    Args:
        page: Playwright Page instance
        link: URL of the event page
        source: Source page configuration dict

    Returns:
        List of event records (can be multiple for series/collection events)
    """
    logging.info(f"\n-> Processing {link} ...")
    records = []

    try:
        page.goto(link, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        delete_cookies_overlay(page)

        ################################################################
        # Extract __NEXT_DATA__ for structured fallback data
        ################################################################
        next_data_ctx = None
        try:
            next_data_el = page.locator("script#__NEXT_DATA__")
            next_data_el.wait_for(state="attached", timeout=5000)
            raw_json = next_data_el.text_content()
            next_data = json.loads(raw_json)
            next_data_ctx = next_data.get("props", {}).get("pageProps", {}).get("context", {})
        except Exception as e:
            logging.debug(f"Could not parse __NEXT_DATA__ on event page: {e}")

        ################################################################
        # Check event status (cancelled, completed)
        ################################################################
        if next_data_ctx:
            basic_info = next_data_ctx.get("basicInfo", {})
            status = basic_info.get("status", "")
            is_cancelled = (
                basic_info.get("isCancelled", False) if "isCancelled" in basic_info else False
            )

            if status == "cancelled" or is_cancelled:
                logging.info("Rejecting record: event cancelled")
                return records
            if status == "completed":
                logging.info("Rejecting record: event completed")
                return records

        ################################################################
        # Is it sold out?
        ################################################################
        sold_out = False
        if next_data_ctx:
            sales_status = next_data_ctx.get("salesStatus", {})
            sales_status_value = sales_status.get("salesStatus", "")
            if sales_status_value in ("sold_out", "sales_ended"):
                sold_out = True

        if sold_out:
            # Eventbrite hides relevant info for sold out events
            logging.info("Rejecting record: sold out")
            return records

        ################################################################
        # Parse event title
        ################################################################
        title_el = page.locator('[data-testid="event-title"]').first
        try:
            title_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
            title = title_el.text_content()
        except PlaywrightTimeoutError:
            # Fallback to __NEXT_DATA__
            if next_data_ctx:
                title = next_data_ctx.get("basicInfo", {}).get("name", "")
            else:
                logging.info("Rejecting record: title not found")
                return records

        if is_plenary(title):
            logging.info("Rejecting record: plenary")
            return records

        ################################################################
        # Is it an online event?
        ################################################################
        online = is_online(title)
        if not online:
            # Check from __NEXT_DATA__
            if next_data_ctx:
                online = next_data_ctx.get("basicInfo", {}).get("isOnline", False)
            # Also check the venue element on the page
            if not online:
                venue_el = page.locator('[data-testid="event-venue"]').first
                try:
                    if venue_el.is_visible(timeout=2000):
                        venue_text = venue_el.text_content()
                        online = is_online(venue_text)
                except PlaywrightTimeoutError:
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
            # Try to get location from the DOM (full address section)
            location_section = page.locator('[data-testid="section-wrapper-location"]').first
            try:
                location_section.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

                # Get venue name
                venue_name_el = location_section.locator("address h3").first
                try:
                    if venue_name_el.is_visible(timeout=2000):
                        location_name = venue_name_el.text_content().strip()
                except PlaywrightTimeoutError:
                    pass

                # Get address lines
                address_lines_els = location_section.locator(
                    'address p[class*="Address_description"]'
                ).all()
                address_parts = []
                for el in address_lines_els:
                    text = el.text_content().strip()
                    if text:
                        address_parts.append(text)
                full_location = ", ".join(filter(None, [location_name] + address_parts))

            except PlaywrightTimeoutError:
                # Fallback: use compact venue text from hero area
                venue_el = page.locator('[data-testid="event-venue"]').first
                try:
                    if venue_el.is_visible(timeout=2000):
                        full_location = venue_el.inner_text().strip()
                except PlaywrightTimeoutError:
                    pass

            if not full_location:
                logging.info("Rejecting record: location not found for in-person event")
                return records

            # Normalize the location string
            full_location = full_location.replace("\n", ", ")
            full_location = " ".join(full_location.split())
            full_location = re.sub(r",\s*,", ",", full_location)
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
        description = ""
        description_el = page.locator('[data-testid="section-wrapper-overview"]').first
        try:
            description_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
            # Click "read more" if present to expand the full description
            read_more_btn = description_el.locator('button[class*="Overview_readMore"]').first
            try:
                if read_more_btn.is_visible(timeout=1000):
                    read_more_btn.click()
                    page.wait_for_timeout(500)
            except PlaywrightTimeoutError:
                pass
            summary_el = description_el.locator('div[class*="Overview_summary"]').first
            description = summary_el.text_content()
        except PlaywrightTimeoutError:
            # Fallback to __NEXT_DATA__
            if next_data_ctx:
                description = next_data_ctx.get("basicInfo", {}).get("summary", "")
                if not description:
                    modules = next_data_ctx.get("structuredContent", {}).get("modules", [])
                    if modules:
                        # Strip HTML tags from the structured content
                        html_desc = modules[0].get("text", "")
                        description = re.sub(r"<[^>]+>", "", html_desc)

        if not description:
            logging.info("Rejecting record: description not found")
            return records

        ################################################################
        # Training?
        ################################################################
        training = is_training(title)

        ################################################################
        # Is it suited for kids?
        ################################################################
        kids = is_for_kids(title)

        ################################################################
        # Determine if this is a series (multiple dates) or single event
        ################################################################
        is_series = False
        if next_data_ctx:
            basic_info = next_data_ctx.get("basicInfo", {})
            is_series = basic_info.get("isSeries", False)

        if not is_series:
            # Also check the date text on the page
            date_el = page.locator('[data-testid="event-datetime"]').first
            try:
                date_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
                date_text = date_el.text_content().strip()
                is_series = bool(
                    re.match(
                        r"(?i)^\s*(multiple dates|plusieurs dates|dates multiples|mehrere termine)\s*$",
                        date_text,
                    )
                )
            except PlaywrightTimeoutError:
                pass

        event_info = []

        if is_series:
            ################################################################
            # Series event: extract dates from the collection modal
            ################################################################
            event_info = extract_series_dates(page, link, next_data_ctx)
        else:
            ################################################################
            # Single event: parse the date from the page
            ################################################################
            event_start_datetime = None
            event_end_datetime = None

            # Try parsing from __NEXT_DATA__ first (most reliable)
            if next_data_ctx:
                basic_info = next_data_ctx.get("basicInfo", {})
                start_date_info = basic_info.get("startDate", {})
                end_date_info = basic_info.get("endDate", {})
                start_local = start_date_info.get("local")
                end_local = end_date_info.get("local")

                if start_local:
                    try:
                        event_start_datetime = parse_iso_datetime(start_local)
                    except ValueError:
                        pass
                if end_local:
                    try:
                        event_end_datetime = parse_iso_datetime(end_local)
                    except ValueError:
                        pass

            # Fallback: parse date text from the DOM
            if not event_start_datetime:
                date_el = page.locator('[data-testid="event-datetime"]').first
                try:
                    date_el.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
                    date_text = date_el.text_content().strip()
                    event_start_datetime, event_end_datetime = get_dates(date_text)
                except (PlaywrightTimeoutError, FreskDateBadFormat) as error:
                    logging.info(f"Rejecting record: {error}")
                    return records

            if not event_end_datetime:
                event_end_datetime = event_start_datetime + timedelta(hours=DEFAULT_DURATION)

            uuid = extract_event_uuid(link)
            if not uuid:
                logging.info("Rejecting record: UUID not found")
                return records

            event_info.append([uuid, event_start_datetime, event_end_datetime, link])

        if not event_info:
            logging.info(f"No valid dates extracted for {link}")
            return records

        ################################################################
        # Build records for all date sessions
        ################################################################
        for uuid, event_start_datetime, event_end_datetime, event_link in event_info:
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
        logging.info(f"Skipping event {link}: {e}")
        return records
    except Exception as e:
        logging.error(f"Unexpected error processing event page {link}: {e}", exc_info=True)
        raise

    return records


def extract_series_dates(page: Page, link: str, next_data_ctx: dict | None) -> list:
    """
    Extract individual session dates from a series/collection event.

    Primary strategy: use the Eventbrite public API
    ``/api/v3/series/{series_id}/events/`` which returns all child events
    with structured start/end datetimes.  No browser modal interaction needed.

    Fallback: open the checkout modal and scrape dates from the calendar or
    list view (legacy approach, kept for resilience).

    Args:
        page: Playwright Page instance
        link: URL of the event page
        next_data_ctx: Parsed __NEXT_DATA__ context dict (or None)

    Returns:
        List of [uuid, start_datetime, end_datetime, link] lists
    """
    event_info = []
    base_uuid = extract_event_uuid(link)
    if not base_uuid:
        logging.warning(f"Could not extract UUID from {link}")
        return event_info

    # ------------------------------------------------------------------
    # Determine the series ID
    # ------------------------------------------------------------------
    series_id = None
    if next_data_ctx:
        basic_info = next_data_ctx.get("basicInfo", {})
        series_id = basic_info.get("seriesId") or basic_info.get("id")
    if not series_id:
        series_id = base_uuid

    # ------------------------------------------------------------------
    # Primary: fetch child events from the Eventbrite API
    # ------------------------------------------------------------------
    event_info = _fetch_series_events_from_api(series_id, link)

    if event_info:
        return event_info

    # ------------------------------------------------------------------
    # Fallback: scrape the checkout modal (legacy approach)
    # ------------------------------------------------------------------
    logging.info("API approach failed, falling back to modal scraping...")
    return _extract_series_dates_from_modal(page, link, base_uuid)


def _fetch_series_events_from_api(series_id: str, link: str) -> list:
    """Fetch child events for a series via the Eventbrite public API.

    Tries both ``.fr`` and ``.com`` domains.  Paginates if necessary.

    Returns:
        List of [uuid, start_datetime, end_datetime, child_link] lists
    """
    event_info = []

    # Determine the domain from the original link
    domains = []
    if "eventbrite.fr" in link:
        domains = ["www.eventbrite.fr", "www.eventbrite.com"]
    else:
        domains = ["www.eventbrite.com", "www.eventbrite.fr"]

    for domain in domains:
        try:
            event_info = _fetch_all_pages(domain, series_id)
            if event_info:
                logging.info(
                    f"Fetched {len(event_info)} child events from API "
                    f"({domain}) for series {series_id}"
                )
                return event_info
        except Exception as e:
            logging.debug(f"API call to {domain} failed: {e}")
            continue

    logging.warning(f"Could not fetch series events from API for series {series_id}")
    return event_info


def _fetch_all_pages(domain: str, series_id: str) -> list:
    """Fetch all pages of child events from the series API endpoint."""
    event_info = []
    page_number = 1

    while True:
        url = (
            f"https://{domain}/api/v3/series/{series_id}/events/"
            f"?page={page_number}&page_size=50"
        )
        logging.debug(f"Fetching series API: {url}")

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            logging.debug(f"HTTP error fetching {url}: {e}")
            raise

        events = data.get("events", [])
        pagination = data.get("pagination", {})

        for ev in events:
            status = ev.get("status", "")
            # Skip completed / cancelled / draft events
            if status not in ("live", "started"):
                logging.debug(
                    f"Skipping child event {ev.get('id')} with status '{status}'"
                )
                continue

            start_info = ev.get("start", {})
            end_info = ev.get("end", {})
            start_local = start_info.get("local")
            end_local = end_info.get("local")

            if not start_local:
                logging.debug(f"Skipping child event {ev.get('id')}: no start date")
                continue

            try:
                start_dt = parse_iso_datetime(start_local)
            except (ValueError, TypeError):
                logging.debug(
                    f"Skipping child event {ev.get('id')}: "
                    f"unparseable start date '{start_local}'"
                )
                continue

            end_dt = None
            if end_local:
                try:
                    end_dt = parse_iso_datetime(end_local)
                except (ValueError, TypeError):
                    pass
            if not end_dt:
                end_dt = start_dt + timedelta(hours=DEFAULT_DURATION)

            child_id = ev.get("id", "")
            child_url = ev.get("url", "")
            # Use the child event's own ID as uuid (unique per occurrence)
            uuid = child_id if child_id else f"{series_id}-{hash(start_local) % 10000}"
            child_link = child_url if child_url else f"https://www.eventbrite.fr/e/{child_id}"

            event_info.append([uuid, start_dt, end_dt, child_link])

        # Handle pagination
        if pagination.get("has_more_items", False):
            page_number += 1
        else:
            break

    return event_info


def _extract_series_dates_from_modal(page: Page, link: str, base_uuid: str) -> list:
    """Legacy fallback: scrape dates from the checkout modal.

    Opens the checkout/availability modal and parses dates from the
    calendar or list view.
    """
    event_info = []

    # Click the checkout/availability button to open the modal
    checkout_button = page.locator(
        '[data-testid="conversion-bar-checkout-button"], '
        "button[id^='check-availability-btn-'], "
        "button[id^='eventbrite-widget-modal-trigger-']"
    ).first

    try:
        checkout_button.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
    except PlaywrightTimeoutError:
        logging.warning(f"No checkout button found for series event {link}")
        return event_info

    try:
        logging.info("Series event detected, clicking checkout button...")
        checkout_button.click()

        # Wait for modal content to load
        # Check for iframe first (Eventbrite sometimes puts the modal in an iframe)
        modal_page = page
        try:
            iframe_locator = page.frame_locator(
                'iframe[id*="eventbrite-widget"], '
                'iframe[class*="modal"], '
                'iframe[title*="availability"]'
            ).first
            test_el = iframe_locator.locator("body").first
            test_el.wait_for(state="attached", timeout=2000)
            modal_page = iframe_locator
            logging.debug("Switching to iframe for modal content")
        except Exception:
            pass

        MODAL_TIMEOUT = 15000

        # Wait for date content to appear in the modal
        date_wrapper_locator = modal_page.locator('p[class*="dateWrapper"]')
        calendar_card_locator = modal_page.locator(
            'div[class*="CompactCalendar"] div[class*="compactChoiceCardContainer"]'
        )

        try:
            modal_page.locator(
                'p[class*="dateWrapper"], '
                'div[class*="CompactCalendar"] div[class*="compactChoiceCardContainer"]'
            ).first.wait_for(state="visible", timeout=MODAL_TIMEOUT)
            logging.debug("Modal content is now visible")
        except PlaywrightTimeoutError:
            logging.warning(f"Modal content did not load within {MODAL_TIMEOUT}ms for {link}")

        date_wrappers = date_wrapper_locator.all()
        calendar_date_cards = calendar_card_locator.all()

        if calendar_date_cards:
            ################################################################
            # Calendar-style modal (CompactCalendar)
            ################################################################
            logging.info(f"Found calendar-style modal with {len(calendar_date_cards)} date cards")

            for card_index, date_card in enumerate(calendar_date_cards):
                try:
                    weekday_el = date_card.locator('p[class*="weekday"]').first
                    day_num_el = date_card.locator('p[class*="dateText"]').first
                    time_slot_el = date_card.locator('p[class*="timeSlot"]').first

                    weekday = weekday_el.text_content()
                    day_num = day_num_el.text_content()
                    time_slot = time_slot_el.text_content()

                    month = "Unknown"
                    try:
                        month_header = modal_page.locator('p[class*="monthName"]').first
                        month = month_header.text_content()
                    except Exception as e:
                        logging.debug(f"Could not find month header: {e}")

                    date_str = f"{weekday}, {month} {day_num} {time_slot}"
                    logging.debug(f"Processing calendar date: {date_str}")

                    try:
                        event_start_datetime, event_end_datetime = get_dates(date_str)
                    except FreskDateBadFormat as error:
                        logging.warning(f"Failed to parse calendar date '{date_str}': {error}")
                        continue

                    unique_suffix = hash(date_str) % 10000
                    uuid = f"{base_uuid}-{unique_suffix}"

                    event_info.append([uuid, event_start_datetime, event_end_datetime, link])
                    logging.debug(f"Added calendar event: {uuid}")

                except Exception as e:
                    logging.warning(f"Failed to process calendar date card {card_index + 1}: {e}")
                    continue

        elif date_wrappers:
            ################################################################
            # List-style modal (dateWrapper + TimeSlotList)
            ################################################################
            logging.info(f"Found {len(date_wrappers)} dates in list-style modal")

            for date_wrapper in date_wrappers:
                try:
                    date_text = date_wrapper.text_content()
                    logging.debug(f"Processing date: {date_text}")

                    # Click on the date card to reveal time slots
                    try:
                        clickable_parent = date_wrapper.locator(
                            'xpath=ancestor::div[contains(@class, "EventInfoCard")]'
                        ).first
                        clickable_parent.click()
                        logging.debug(f"Clicked on date card for: {date_text}")

                        time_slot_list = modal_page.locator('ul[class*="TimeSlotList"]').first
                        try:
                            time_slot_list.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)
                        except PlaywrightTimeoutError:
                            logging.warning(f"Time slot list did not load for date: {date_text}")
                            continue

                        page.wait_for_timeout(500)
                    except Exception as e:
                        logging.debug(f"Could not click date card: {e}")

                    # Find all time slots
                    all_time_slot_lists = modal_page.locator('ul[class*="TimeSlotList"]').all()
                    if not all_time_slot_lists:
                        logging.warning(f"No time slot lists found for date: {date_text}")
                        continue

                    time_slots_data = []
                    for time_slot_list in all_time_slot_lists:
                        time_slot_lis = time_slot_list.locator("li").all()
                        for time_slot_li in time_slot_lis:
                            try:
                                time_element = time_slot_li.locator('p[class*="sessionText"]').first
                                time_text = time_element.text_content()
                                if time_text:
                                    time_slots_data.append(time_text)
                            except Exception as e:
                                logging.debug(f"Could not extract time slot text: {e}")
                                continue

                    if not time_slots_data:
                        logging.warning(f"No time slots found for date: {date_text}")
                        continue

                    logging.debug(f"Found {len(time_slots_data)} time slots for date: {date_text}")

                    for time_text in time_slots_data:
                        try:
                            combined_text = f"{date_text} {time_text}"
                            logging.debug(f"Processing time slot: {combined_text}")

                            try:
                                event_start_datetime, event_end_datetime = get_dates(combined_text)
                            except FreskDateBadFormat as error:
                                logging.warning(f"Failed to parse date '{combined_text}': {error}")
                                continue

                            unique_suffix = hash(combined_text) % 10000
                            uuid = f"{base_uuid}-{unique_suffix}"

                            event_info.append(
                                [uuid, event_start_datetime, event_end_datetime, link]
                            )
                            logging.debug(f"Added event: {uuid}")

                        except Exception as e:
                            logging.warning(f"Failed to process time slot '{time_text}': {e}")
                            continue

                except Exception as e:
                    logging.warning(f"Failed to process date wrapper: {e}")
                    continue

        if not event_info:
            logging.warning(f"No valid events extracted from series modal for {link}")

    except Exception as e:
        logging.error(f"Failed to process series modal for {link}: {e}", exc_info=True)

    return event_info
