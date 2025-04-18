import json
import re
import time
import logging

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from db.records import get_record_dict
from utils.date_and_time import get_dates
from utils.errors import FreskError, FreskDateBadFormat, FreskLanguageNotRecognized
from utils.keywords import *
from utils.language import get_language_code
from utils.location import get_address


def get_fdc_data(sources, service, options):
    logging.info("Scraping data from fresqueduclimat.org")

    driver = webdriver.Firefox(service=service, options=options)

    records = []

    for page in sources:
        logging.info("========================")
        driver.get(page["url"])
        driver.implicitly_wait(2)

        wait = WebDriverWait(driver, 10)
        iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
        driver.switch_to.frame(iframe)

        while True:
            ele = driver.find_elements(By.CSS_SELECTOR, "a.link-dark")
            links = [e.get_attribute("href") for e in ele]

            for link in links:
                logging.info(f"\n-> Processing {link} ...")
                driver.get(link)
                driver.implicitly_wait(3)

                ################################################################
                # Parse event id
                ################################################################
                # Define the regex pattern for UUIDs
                uuid_pattern = (
                    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
                )
                uuids = re.findall(uuid_pattern, link)
                if not uuids:
                    logging.info("Rejecting record: UUID not found")
                    driver.back()
                    wait = WebDriverWait(driver, 10)
                    iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
                    driver.switch_to.frame(iframe)
                    continue

                ################################################################
                # Parse event title
                ################################################################
                title_el = driver.find_element(
                    by=By.TAG_NAME,
                    value="h3",
                )
                title = title_el.text

                ################################################################
                # Parse start and end dates
                ################################################################
                clock_icon = driver.find_element(By.CLASS_NAME, "fa-clock")
                parent_div = clock_icon.find_element(By.XPATH, "..")
                event_time = parent_div.text

                try:
                    event_start_datetime, event_end_datetime = get_dates(event_time)
                except FreskDateBadFormat as error:
                    logging.info(f"Reject record: {error}")
                    driver.back()
                    wait = WebDriverWait(driver, 10)
                    iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
                    driver.switch_to.frame(iframe)
                    continue

                ################################################################
                # Workshop language
                ################################################################
                language_code = None
                try:
                    globe_in_event = driver.find_element(
                        By.XPATH, '//div[contains(@class, "mb-3")]/i[contains(@class, "fa-globe")]'
                    )
                    parent = globe_in_event.find_element(By.XPATH, "..")
                    language_code = get_language_code(parent.text)
                except FreskLanguageNotRecognized as e:
                    logging.warning(f"Assuming workshop language as French: {e}")
                    language_code = "fr"
                except NoSuchElementException:
                    logging.warning("Unable to find workshop language, assuming French.")
                    language_code = "fr"

                ################################################################
                # Is it an online event?
                ################################################################
                online = True
                try:
                    driver.find_element(By.CLASS_NAME, "fa-video")
                except NoSuchElementException:
                    online = False

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
                    pin_icon = driver.find_element(By.CLASS_NAME, "fa-map-pin")
                    parent_div = pin_icon.find_element(By.XPATH, "..")
                    full_location = parent_div.text

                    try:
                        logging.info(f"Full location: {full_location}")
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
                        wait = WebDriverWait(driver, 10)
                        iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
                        driver.switch_to.frame(iframe)
                        continue

                ################################################################
                # Description
                ################################################################
                description_title_el = driver.find_element(
                    By.XPATH, "//strong[text()='Description']"
                )
                parent_description_el = description_title_el.find_element(By.XPATH, "..")
                description = parent_description_el.text

                ################################################################
                # Training?
                ################################################################
                training = is_training(title)

                ################################################################
                # Is it full?
                ################################################################
                user_icon = driver.find_element(By.CLASS_NAME, "fa-user")
                parent_container = user_icon.find_element(By.XPATH, "../..")
                sold_out = is_sold_out(parent_container.text)

                ################################################################
                # Is it suited for kids?
                ################################################################
                kids = is_for_kids(description) and not training

                ################################################################
                # Parse tickets link
                ################################################################
                user_icon = driver.find_element(By.CLASS_NAME, "fa-user")
                parent_link = user_icon.find_element(By.XPATH, "..")
                tickets_link = parent_link.get_attribute("href")

                ################################################################
                # Building final object
                ################################################################
                record = get_record_dict(
                    f"{page['id']}-{uuids[0]}",
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
                    language_code,
                    online,
                    training,
                    sold_out,
                    kids,
                    link,
                    tickets_link,
                    description,
                )

                records.append(record)
                logging.info(f"Successfully scraped {link}\n{json.dumps(record, indent=4)}")

                driver.back()
                wait = WebDriverWait(driver, 10)
                iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
                driver.switch_to.frame(iframe)

            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                driver.implicitly_wait(2)
                time.sleep(2)
                next_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            "//a[@class='page-link' and contains(text(), 'Suivant')]",
                        )
                    )
                )
                next_button.location_once_scrolled_into_view
                time.sleep(2)
                next_button.click()
                time.sleep(10)
            except TimeoutException:
                break

    driver.quit()

    return records
