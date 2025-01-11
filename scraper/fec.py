import json
import time

from datetime import datetime
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from db.records import get_record_dict
from utils.errors import (
    FreskError,
    FreskDateBadFormat,
    FreskDateNotFound,
    FreskDateDifferentTimezone,
)
from utils.keywords import *
from utils.location import get_address


def extract_dates(driver):
    try:
        date_info_el = driver.find_element(
            by=By.CSS_SELECTOR,
            value='p[data-hook="event-full-date"]',
        )
        event_time = date_info_el.text
    except NoSuchElementException:
        raise FreskDateNotFound

    month_mapping = {
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

    date_and_times = event_time.split(",")
    day_string = date_and_times[0].split(" ")
    if len(day_string) == 2:
        day = day_string[0]
        month_string = day_string[1]
        year = 2025
    elif len(day_string) == 3:
        day = day_string[0]
        month_string = day_string[1]
        year = day_string[2]
    else:
        raise FreskDateBadFormat(event_time)

    times_and_timezone = date_and_times[1].split(" UTC")
    if len(times_and_timezone) >= 2:
        if not times_and_timezone[1] in (
            "+1",
            "+2",
        ):
            raise FreskDateDifferentTimezone(event_time)

    times = times_and_timezone[0].split(" – ")

    try:
        # Extract hours and minutes from time strings
        start_hour, start_minute = map(int, times[0].split(":"))
        end_hour, end_minute = map(int, times[1].split(":"))

        # Construct the datetime objects
        event_start_datetime = datetime(
            int(year),
            month_mapping[month_string],
            int(day),
            start_hour,
            start_minute,
        )
        event_end_datetime = datetime(
            int(year),
            month_mapping[month_string],
            int(day),
            end_hour,
            end_minute,
        )

        return event_start_datetime, event_end_datetime
    except Exception:
        raise FreskDateBadFormat(event_time)


def scroll_to_bottom(driver):
    while True:
        print("Scrolling to the bottom...")
        try:
            time.sleep(2)
            next_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(
                    (
                        By.CSS_SELECTOR,
                        'button[data-hook="load-more-button"]',
                    )
                )
            )
            desired_y = (next_button.size["height"] / 2) + next_button.location["y"]
            window_h = driver.execute_script("return window.innerHeight")
            window_y = driver.execute_script("return window.pageYOffset")
            current_y = (window_h / 2) + window_y
            scroll_y_by = desired_y - current_y
            driver.execute_script("window.scrollBy(0, arguments[0]);", scroll_y_by)
            time.sleep(2)
            next_button.click()
        except TimeoutException:
            break


def get_fec_data(sources, service, options):
    print("Scraping data from lafresquedeleconomiecirculaire.com")

    driver = webdriver.Firefox(service=service, options=options)

    records = []

    for page in sources:
        print("========================")
        driver.get(page["url"])
        driver.implicitly_wait(2)

        # Scroll to bottom to load all events
        scroll_to_bottom(driver)
        driver.execute_script("window.scrollTo(0, 0);")

        ele = driver.find_elements(
            By.CSS_SELECTOR, 'li[data-hook="events-card"] div[data-hook="title"] a'
        )
        links = [e.get_attribute("href") for e in ele]

        # Only events published on lafresquedeleconomiecirculaire.com can be extracted
        links = [l for l in links if "lafresquedeleconomiecirculaire.com" in l]

        for link in links:
            print(f"\n-> Processing {link} ...")
            driver.get(link)
            driver.implicitly_wait(3)
            time.sleep(5)

            ################################################################
            # Parse event id
            ################################################################
            # Define the regex pattern for UUIDs
            uuid = link.split("/event-details/")[-1]
            if not uuid:
                print("Rejecting record: UUID not found")
                continue

            ################################################################
            # Parse event title
            ################################################################
            title_el = driver.find_element(
                by=By.TAG_NAME,
                value="h1",
            )
            title = title_el.text

            ################################################################
            # Parse start and end dates
            ################################################################
            try:
                event_start_datetime, event_end_datetime = extract_dates(driver)
            except FreskError as error:
                print(f"Reject record: {error}")
                continue

            ################################################################
            # Is it an online event?
            ################################################################
            online = False
            try:
                online_el = driver.find_element(
                    By.CSS_SELECTOR, 'p[data-hook="event-full-location"]'
                )
                if is_online(online_el.text):
                    online = True
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
                location_el = driver.find_element(
                    By.CSS_SELECTOR, 'p[data-hook="event-full-location"]'
                )
                full_location = location_el.text

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
            driver.execute_script("window.scrollBy(0, document.body.scrollHeight);")

            # Click on "show more" button
            try:
                show_more_el = driver.find_element(
                    By.CSS_SELECTOR, 'button[data-hook="about-section-button"]'
                )
                show_more_el.click()
            except NoSuchElementException:
                pass

            try:
                description_el = driver.find_element(
                    By.CSS_SELECTOR, 'div[data-hook="about-section-text"]'
                )
            except NoSuchElementException:
                try:
                    description_el = driver.find_element(
                        By.CSS_SELECTOR, 'div[data-hook="about-section"]'
                    )
                except NoSuchElementException:
                    print(f"Rejecting record: no description")
                    continue

            description = description_el.text

            ################################################################
            # Training?
            ################################################################
            training = is_training(title)

            ################################################################
            # Is it full?
            ################################################################
            sold_out = True
            try:
                _ = driver.find_element(
                    by=By.CSS_SELECTOR,
                    value='div[data-hook="event-sold-out"]',
                )
            except NoSuchElementException:
                sold_out = False

            ################################################################
            # Is it suited for kids?
            ################################################################
            kids = is_for_kids(title)

            ################################################################
            # Parse tickets link
            ################################################################
            tickets_link = link

            ################################################################
            # Building final object
            ################################################################
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
                tickets_link,
                description,
            )

            records.append(record)
            print(f"Successfully scraped {link}\n{json.dumps(record, indent=4)}")

    driver.quit()

    return records
