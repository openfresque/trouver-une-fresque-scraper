import numpy as np
import time
import json
import re

from datetime import datetime
from selenium import webdriver
from selenium.common.exceptions import (
    StaleElementReferenceException,
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from db.records import get_record_dict
from utils.errors import FreskError, FreskDateBadFormat, FreskDateNotFound
from utils.keywords import *
from utils.location import get_address


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
        print(f"Transcend consent manager element couldn't be removed: {e}")


def extract_dates(driver):
    try:
        date_info_el = driver.find_element(
            by=By.CSS_SELECTOR,
            value="span.date-info__full-datetime",
        )
        event_time = date_info_el.text
    except NoSuchElementException:
        raise FreskDateNotFound

    months = {
        "janv.": 1,
        "févr.": 2,
        "mars": 3,
        "avr.": 4,
        "mai": 5,
        "juin": 6,
        "juil.": 7,
        "août": 8,
        "sept.": 9,
        "oct.": 10,
        "nov.": 11,
        "déc.": 12,
    }

    try:
        parts = event_time.split()
        day = int(parts[1])
        month = months[parts[2]]
        year = int(parts[3])
        start_time = parts[4]
        end_time = parts[6]

        # Convert time strings to datetime objects
        event_start_datetime = datetime(
            year,
            month,
            day,
            int(start_time.split(":")[0]),
            int(start_time.split(":")[1]),
        )
        event_end_datetime = datetime(
            year,
            month,
            day,
            int(end_time.split(":")[0]),
            int(end_time.split(":")[1]),
        )

        return event_start_datetime, event_end_datetime
    except Exception:
        raise FreskDateBadFormat(event_time)


def scroll_to_bottom(driver):
    more_content = True
    while more_content:
        print("Scrolling to the bottom...")
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
    print("Scraping data from eventbrite.fr")

    driver = webdriver.Firefox(service=service, options=options)

    records = []

    for page in sources:
        print(f"==================\nProcessing page {page}")
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

        print(f"Found {len(event_card_divs)} events")

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
            print(f"\n-> Processing {link} ...")
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
                        print("Rejecting record: event expired")
                        continue
                except StaleElementReferenceException:
                    if driver.find_element(
                        By.XPATH, '//div[@data-testid="enhancedExpiredEventsBadge"]'
                    ).find_elements(By.XPATH, "./*"):
                        print("Rejecting record: event expired")
                        continue

            except NoSuchElementException:
                pass

            try:
                badge = driver.find_element(By.CSS_SELECTOR, "div.enhanced-expired-badge")
                print("Rejecting record: event expired")
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
                print("Rejecting record: sold out")
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
                print("Rejecting record: plénière")
                continue

            ###########################################################
            # Is it an online event?
            ################################################################
            online = False
            try:
                online_el = driver.find_element(By.CSS_SELECTOR, "p.location-info__address-text")
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

            if not online:
                location_el = driver.find_element(By.CSS_SELECTOR, "div.location-info__address")
                full_location_text = location_el.text.split("\n")
                location_name = full_location_text[0]
                address_and_city = full_location_text[1]
                full_location = f"{location_name}, {address_and_city}"

                try:
                    address_dict = get_address(full_location)
                    (
                        location_name,
                        address,
                        city,
                        department,
                        zip_code,
                        latitude,
                        longitude,
                    ) = address_dict.values()
                except FreskError as error:
                    print(f"Rejecting record: {error}.")
                    continue

            ################################################################
            # Description
            ################################################################
            try:
                description_title_el = driver.find_element(By.CSS_SELECTOR, "div.eds-text--left")
                description = description_title_el.text
            except NoSuchElementException:
                print("Rejecting record: Description not found.")
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
                            event_start_datetime, event_end_datetime = extract_dates(driver)
                        except FreskError as error:
                            print(f"Reject record: {error}")
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
                                [uuid, event_start_datetime, event_end_datetime, tickets_link]
                            )

            # There is only one event on this page.
            except TimeoutException:
                ################################################################
                # Dates
                ################################################################
                try:
                    event_start_datetime, event_end_datetime = extract_dates(driver)
                except FreskDateBadFormat as error:
                    print(f"Reject record: {error}")
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
            for index, (uuid, event_start_datetime, event_end_datetime, link) in enumerate(
                event_info
            ):
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
                    latitude,
                    longitude,
                    online,
                    training,
                    sold_out,
                    kids,
                    link,
                    link,
                    description,
                )
                records.append(record)
                print(f"Successfully scraped {link}\n{json.dumps(record, indent=4)}")

    driver.quit()

    return records
