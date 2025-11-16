import numpy as np
import time
import json
import logging
import re

from selenium import webdriver
from selenium.common.exceptions import (
    StaleElementReferenceException,
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from trouver_une_fresque_scraper.db.records import get_record_dict
from trouver_une_fresque_scraper.utils.date_and_time import get_dates_from_element
from trouver_une_fresque_scraper.utils.errors import (
    FreskError,
    FreskDateBadFormat,
    FreskDateNotFound,
)
from trouver_une_fresque_scraper.utils.keywords import *
from trouver_une_fresque_scraper.utils.language import detect_language_code
from trouver_une_fresque_scraper.utils.location import get_address


def delete_cookies_overlay(driver):
    try:
        transcend_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#transcend-consent-manager"))
        )

        # Use JavaScript to remove the transcend-consent-manager element
        script = """
        var element = arguments[0];
        element.parentNode.removeChild(element);
        """
        driver.execute_script(script, transcend_element)
    except Exception as e:
        logging.info(f"Transcend consent manager element couldn't be removed: {e}")


def scroll_to_bottom(driver):
    more_content = True
    while more_content:
        logging.info("Scrolling to the bottom...")
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(5)  # Give the page some time to load new content

            # Function to safely click the next button
            def click_next_button():
                try:
                    next_button = WebDriverWait(driver, 10).until(
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

                except StaleElementReferenceException:
                    click_next_button()  # Retry if the element is stale

            click_next_button()

        except TimeoutException:
            more_content = False


def get_eventbrite_data(sources, service, options):
    logging.info("Scraping data from eventbrite.fr")

    driver = webdriver.Firefox(service=service, options=options)

    records = []

    for page in sources:
        logging.info(f"==================\nProcessing page {page}")
        driver.get(page["url"])
        driver.implicitly_wait(5)

        # Scroll to bottom to load all events
        scroll_to_bottom(driver)
        driver.execute_script("window.scrollTo(0, 0);")

        elements = []
        future_events = driver.find_element(
            By.CSS_SELECTOR, 'div[data-testid="organizer-profile__future-events"]'
        )
        event_card_divs = future_events.find_elements(By.CSS_SELECTOR, "div.event-card")

        logging.info(f"Found {len(event_card_divs)} events")

        for event_card_div in event_card_divs:
            link_elements = event_card_div.find_elements(By.CSS_SELECTOR, "a.event-card-link")
            elements.extend(link_elements)

        links = []
        for link_element in elements:
            href = link_element.get_attribute("href")
            if href:
                links.append(href)
        links = np.unique(links)

        for link in links:
            logging.info(f"\n-> Processing {link} ...")
            driver.get(link)
            delete_cookies_overlay(driver)
            driver.implicitly_wait(3)
            time.sleep(3)  # Pages are quite long to load

            ################################################################
            # Has it expired?
            ################################################################
            try:
                badge = driver.find_element(
                    By.XPATH, '//div[@data-testid="enhancedExpiredEventsBadge"]'
                )
                # If the element has children elements, it is enabled
                try:
                    if badge.find_elements(By.XPATH, "./*"):
                        logging.info("Rejecting record: event expired")
                        continue
                except StaleElementReferenceException:
                    if driver.find_element(
                        By.XPATH, '//div[@data-testid="enhancedExpiredEventsBadge"]'
                    ).find_elements(By.XPATH, "./*"):
                        logging.info("Rejecting record: event expired")
                        continue

            except NoSuchElementException:
                pass

            try:
                badge = driver.find_element(By.CSS_SELECTOR, "div.enhanced-expired-badge")
                logging.info("Rejecting record: event expired")
                continue
            except NoSuchElementException:
                pass

            ################################################################
            # Is it full?
            ################################################################
            sold_out = False
            try:
                badge = driver.find_element(By.XPATH, '//div[@data-testid="salesEndedMessage"]')
                # If the element has children elements, it is enabled
                sold_out = bool(badge.find_elements(By.XPATH, "./*"))
            except NoSuchElementException:
                pass

            if sold_out:
                # We reject sold out events as the Eventbrite UX hides
                # relevant info in this case (which looks like an awful practice)
                logging.info("Rejecting record: sold out")
                continue

            ################################################################
            # Parse event title
            ################################################################
            title_el = driver.find_element(
                by=By.TAG_NAME,
                value="h1",
            )
            title = title_el.text

            if is_plenary(title):
                logging.info("Rejecting record: plénière")
                continue

            ###########################################################
            # Is it an online event?
            ################################################################
            online = is_online(title)
            if not online:
                try:
                    online_el = driver.find_element(
                        By.CSS_SELECTOR, "span.start-date-and-location__location"
                    )
                    online = is_online(online_el.text)
                except NoSuchElementException:
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
                location_el = driver.find_element(
                    By.CSS_SELECTOR, ".start-date-and-location__location"
                )
                full_location = location_el.text.replace("\n", ", ")

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

            ################################################################
            # Description
            ################################################################
            try:
                description_title_el = driver.find_element(By.CSS_SELECTOR, "div.event-description")
                description = description_title_el.text
            except NoSuchElementException:
                logging.info("Rejecting record: Description not found.")
                continue

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

            try:
                date_time_div = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.select-date-and-time"))
                )
                if date_time_div:
                    driver.execute_script("window.scrollBy(0, arguments[0]);", 800)

                    li_elements = date_time_div.find_elements(
                        By.CSS_SELECTOR, "li:not([data-heap-id])"
                    )
                    for li in li_elements:
                        clickable_li = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable(li)
                        )
                        clickable_li.click()

                        ################################################################
                        # Dates
                        ################################################################
                        try:
                            date_info_el = driver.find_element(
                                by=By.CSS_SELECTOR,
                                value="span.date-info__full-datetime",
                            )
                        except NoSuchElementException:
                            raise FreskDateNotFound

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

            # There is only one event on this page.
            except TimeoutException:
                ################################################################
                # Dates
                ################################################################
                try:
                    date_info_el = driver.find_element(
                        by=By.CSS_SELECTOR,
                        value="span.date-info__full-datetime",
                    )
                except NoSuchElementException:
                    raise FreskDateNotFound

                try:
                    event_start_datetime, event_end_datetime = get_dates_from_element(date_info_el)
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

    driver.quit()

    return records
