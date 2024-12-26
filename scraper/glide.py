import time
import re
import json

from datetime import datetime
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from db.records import get_record_dict
from utils.errors import FreskError
from utils.keywords import *
from utils.location import get_address


def get_glide_data(sources, service, options):
    print("Scraping data from glide.page")

    driver = webdriver.Firefox(service=service, options=options)

    records = []

    for page in sources:
        print(f"==================\nProcessing page {page}")
        driver.get(page["url"])
        driver.implicitly_wait(10)
        time.sleep(20)

        tab_button_element = driver.find_element(
            By.XPATH,
            f"//div[contains(@class, 'button-text') and text()='{page['filter']}']",
        )
        tab_button_element.click()

        # Maybe there are multiple pages, so we loop.
        while True:
            time.sleep(5)
            ele = driver.find_elements(
                By.XPATH, "//div[contains(@class, 'collection-item') and @role='button']"
            )
            num_el = len(ele)
            print(f"Found {num_el} elements")

            for i in range(num_el):
                time.sleep(5)
                ele = driver.find_elements(
                    By.XPATH, "//div[contains(@class, 'collection-item') and @role='button']"
                )

                # The following is ugly, but necessary as elements are loaded dynamically in JS.
                # We have to make sure that all elements are loaded before proceeding.
                max_tries = 10
                count = 0
                while len(ele) != num_el:
                    driver.refresh()
                    time.sleep(5)
                    ele = driver.find_elements(
                        By.XPATH, "//div[contains(@class, 'collection-item') and @role='button']"
                    )

                    count += 1
                    if count == max_tries:
                        raise RuntimeError(
                            f"Cannot load the {num_el} JS elements after {count} tries."
                        )

                el = ele[i]
                el.click()

                time.sleep(5)
                link = driver.current_url
                print(f"\n-> Processing {link} ...")
                driver.implicitly_wait(3)

                ################################################################
                # Is it canceled?
                ################################################################
                try:
                    # Attempt to find the div element by its id
                    large_title_el = driver.find_element(By.CSS_SELECTOR, "h2.headlineMedium")
                    large_title = large_title_el.text
                    if is_canceled(large_title):
                        print("Rejecting record: canceled")
                        driver.back()
                        continue
                except NoSuchElementException:
                    pass

                ################################################################
                # Parse event id
                ################################################################
                uuid = link.split("/")[-1]
                if not uuid:
                    print("Rejecting record: UUID not found")
                    driver.back()
                    continue

                ################################################################
                # Parse event title
                ################################################################
                title_el = driver.find_element(by=By.CSS_SELECTOR, value="h2.headlineSmall")
                title = title_el.text

                ################################################################
                # Parse start and end dates
                ################################################################
                time_el = driver.find_element(
                    by=By.XPATH,
                    value="//li/div[contains(text(), 'Date')]",
                )
                parent_el = time_el.find_element(by=By.XPATH, value="..")
                event_time_el = parent_el.find_element(by=By.XPATH, value="./*[2]")
                event_time = event_time_el.text.lower()

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

                year = 2024
                year_pattern = r"\b\d{4}\b"
                year_match = re.search(year_pattern, event_time)
                if year_match:
                    year = year_match.group()
                    event_time = re.sub(f" {year_pattern}", "", event_time)

                date_and_times = event_time.split(" de ")
                try:
                    _, day, month_string = date_and_times[0].split(" ")
                except ValueError:
                    print("Rejecting record: error while parsing the event date")
                    driver.back()
                    continue

                # Define a regular expression pattern to extract times
                time_pattern = r"(\d{1,2}h\d{2}) à (\d{1,2}h\d{2})"

                # Find matches using the pattern
                matches = re.findall(time_pattern, date_and_times[1])
                if matches:
                    start_time, end_time = matches[0]
                else:
                    print("Rejecting record: bad format in dates")
                    driver.back()
                    continue

                # Extract hours and minutes from time strings
                start_hour, start_minute = map(int, start_time.split("h"))
                end_hour, end_minute = map(int, end_time.split("h"))

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

                ################################################################
                # Is it an online event?
                ################################################################
                time_label_el = driver.find_element(
                    by=By.XPATH,
                    value="//li/div[contains(text(), 'Format')]",
                )
                parent_el = time_label_el.find_element(by=By.XPATH, value="..")
                online_el = parent_el.find_element(by=By.XPATH, value="./*[2]")
                online = is_online(online_el.text)

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
                        address_label_el = driver.find_element(
                            by=By.XPATH,
                            value="//li/div[contains(text(), 'Adresse')]",
                        )
                        parent_el = address_label_el.find_element(by=By.XPATH, value="..")
                        address_el = parent_el.find_element(by=By.XPATH, value="./*[2]")
                    except Exception:
                        print("Rejecting record: empty address")
                        driver.back()
                        continue

                    full_location = address_el.text

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
                        driver.back()
                        continue

                ################################################################
                # Description
                ################################################################
                description_label_el = driver.find_element(
                    by=By.XPATH,
                    value="//li/div[contains(text(), 'Description')]",
                )
                parent_el = description_label_el.find_element(by=By.XPATH, value="..")
                description_el = parent_el.find_element(by=By.XPATH, value="./*[2]")
                description = description_el.text

                ################################################################
                # Training?
                ################################################################
                training = is_training(title)

                ################################################################
                # Is it full?
                ################################################################
                attendees_label_el = driver.find_element(
                    by=By.XPATH,
                    value="//li/div[contains(text(), 'participant')]",
                )
                parent_el = attendees_label_el.find_element(by=By.XPATH, value="..")
                attendees_el = parent_el.find_element(by=By.XPATH, value="./*[2]")
                attendees = attendees_el.text

                sold_out = attendees.split("/")[0] == attendees.split("/")[1]

                ################################################################
                # Is it suited for kids?
                ################################################################
                kids = False

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

                driver.back()

            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                driver.implicitly_wait(2)
                time.sleep(2)
                next_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            "//button[@aria-label='Next']",
                        )
                    )
                )
                next_button.location_once_scrolled_into_view
                time.sleep(2)
                next_button.click()
                time.sleep(2)
            except TimeoutException:
                break

    driver.quit()

    return records
