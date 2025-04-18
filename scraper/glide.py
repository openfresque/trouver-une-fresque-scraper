import time
import re
import json
import logging

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from db.records import get_record_dict
from utils.date_and_time import get_dates
from utils.errors import FreskError
from utils.keywords import *
from utils.location import get_address


def get_glide_data(sources, service, options):
    logging.info("Scraping data from glide.page")

    driver = webdriver.Firefox(service=service, options=options)

    records = []

    for page in sources:
        logging.info(f"==================\nProcessing page {page}")
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
                By.XPATH,
                "//div[contains(@class, 'collection-item') and @role='button']",
            )
            num_el = len(ele)
            logging.info(f"Found {num_el} elements")

            for i in range(num_el):
                time.sleep(5)
                ele = driver.find_elements(
                    By.XPATH,
                    "//div[contains(@class, 'collection-item') and @role='button']",
                )

                # The following is ugly, but necessary as elements are loaded dynamically in JS.
                # We have to make sure that all elements are loaded before proceeding.
                max_tries = 10
                count = 0
                while len(ele) != num_el:
                    driver.refresh()
                    time.sleep(5)
                    ele = driver.find_elements(
                        By.XPATH,
                        "//div[contains(@class, 'collection-item') and @role='button']",
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
                logging.info(f"\n-> Processing {link} ...")
                driver.implicitly_wait(3)

                ################################################################
                # Is it canceled?
                ################################################################
                try:
                    # Attempt to find the div element by its id
                    large_title_el = driver.find_element(By.CSS_SELECTOR, "h2.headlineMedium")
                    large_title = large_title_el.text
                    if is_canceled(large_title):
                        logging.info("Rejecting record: canceled")
                        driver.back()
                        continue
                except NoSuchElementException:
                    pass

                ################################################################
                # Parse event id
                ################################################################
                uuid = link.split("/")[-1]
                if not uuid:
                    logging.info("Rejecting record: UUID not found")
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

                try:
                    event_start_datetime, event_end_datetime = get_dates(event_time)
                except Exception as e:
                    logging.info(f"Rejecting record: {e}")
                    driver.back()
                    continue

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
                country_code = ""

                if not online:
                    try:
                        address_label_el = driver.find_element(
                            by=By.XPATH,
                            value="//li/div[contains(text(), 'Adresse')]",
                        )
                        parent_el = address_label_el.find_element(by=By.XPATH, value="..")
                        address_el = parent_el.find_element(by=By.XPATH, value="./*[2]")
                    except Exception:
                        logging.info("Rejecting record: empty address")
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
                            country_code,
                            latitude,
                            longitude,
                        ) = address_dict.values()
                    except FreskError as error:
                        logging.info(f"Rejecting record: {error}.")
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
                    country_code,
                    latitude,
                    longitude,
                    page["language_code"],
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
