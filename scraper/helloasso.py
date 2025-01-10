import json
import re
import time

from datetime import datetime
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from db.records import get_record_dict
from utils.errors import FreskError, FreskDateNotFound, FreskDateBadFormat
from utils.keywords import *
from utils.location import get_address


def extract_dates(driver):
    try:
        date_info_el = driver.find_element(
            by=By.CSS_SELECTOR,
            value="span.CampaignHeader--Date",
        )
        event_time = date_info_el.text
    except NoSuchElementException:
        raise FreskDateNotFound

    month_mapping = {
        "janvier": 1,
        "février": 2,
        "mars": 3,
        "avril": 4,
        "mai": 5,
        "juin": 6,
        "juillet": 7,
        "août": 8,
        "septembre": 9,
        "octobre": 10,
        "novembre": 11,
        "décembre": 12,
    }

    # Expected date format is Le 17 juillet 2025, de 18h à 20h30
    date_and_times = event_time.split(",")
    day_string = date_and_times[0].replace("Le ", "")
    day_string = day_string.split(" ")

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

    # Define a regular expression pattern to extract times
    time_pattern = r"(\d{1,2}h\d{0,2}) à (\d{1,2}h\d{0,2})"

    # Find matches using the pattern
    matches = re.findall(time_pattern, date_and_times[1])
    if matches:
        start_time, end_time = matches[0]
    else:
        raise FreskDateBadFormat(event_time)

    try:
        # Extract hours and minutes from time strings
        start_parts = [part for part in start_time.split("h") if part]
        start_hour = int(start_parts[0])
        start_minute = int(start_parts[1]) if len(start_parts) > 1 else 0

        end_parts = [part for part in end_time.split("h") if part]
        end_hour = int(end_parts[0])
        end_minute = int(end_parts[1]) if len(end_parts) > 1 else 0

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


def get_helloasso_data(sources, service, options):
    print("Scraping data from helloasso.com")

    driver = webdriver.Firefox(service=service, options=options)

    records = []

    for page in sources:
        print(f"==================\nProcessing page {page}")
        driver.get(page["url"])
        driver.implicitly_wait(5)
        time.sleep(3)

        # Scroll to bottom to load all events
        desired_y = 2300
        window_h = driver.execute_script("return window.innerHeight")
        window_y = driver.execute_script("return window.pageYOffset")
        current_y = (window_h / 2) + window_y
        scroll_y_by = desired_y - current_y
        driver.execute_script("window.scrollBy(0, arguments[0]);", scroll_y_by)
        time.sleep(5)

        try:
            button = driver.find_element(
                By.XPATH,
                '//button[@data-ux="Explore_OrganizationPublicPage_Actions_ActionEvent_ShowAllActions"]',
            )
            button.click()
        except NoSuchElementException:
            pass

        ele = driver.find_elements(By.CSS_SELECTOR, "a.ActionLink-Event")
        links = [e.get_attribute("href") for e in ele]
        num_el = len(ele)
        print(f"Found {num_el} elements")

        for link in links:
            print(f"\n-> Processing {link} ...")
            driver.get(link)
            driver.implicitly_wait(3)

            ################################################################
            # Parse event id
            ################################################################
            uuid = link.split("/")[-1]
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

            if not online:
                try:
                    location_el = driver.find_element(
                        By.CSS_SELECTOR, "section.CardAddress--Location"
                    )
                except NoSuchElementException:
                    print("Rejecting record: no location")
                    continue

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
            try:
                description_el = driver.find_element(
                    By.CSS_SELECTOR, "div.CampaignHeader--Description"
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
                link,
                description,
            )

            records.append(record)
            print(f"Successfully scraped {link}\n{json.dumps(record, indent=4)}")

    driver.quit()

    return records
