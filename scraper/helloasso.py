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
from utils.errors import FreskError, FreskDateNotFound, FreskDateBadFormat
from utils.keywords import *
from utils.location import get_address


def scroll_to_bottom(driver):
    while True:
        logging.info("Scrolling to the bottom...")
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
    logging.info("Scraping data from helloasso.com")

    driver = webdriver.Firefox(service=service, options=options)

    records = []

    for page in sources:
        logging.info(f"==================\nProcessing page {page}")
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
        logging.info(f"Found {num_el} elements")

        for link in links:
            logging.info(f"\n-> Processing {link} ...")
            driver.get(link)
            driver.implicitly_wait(3)

            ################################################################
            # Parse event id
            ################################################################
            uuid = link.split("/")[-1]
            if not uuid:
                logging.info("Rejecting record: UUID not found")
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
                date_info_el = driver.find_element(
                    by=By.CSS_SELECTOR,
                    value="span.CampaignHeader--Date",
                )
                event_time = date_info_el.text
            except NoSuchElementException as error:
                logging.info(f"Reject record: {error}")
                continue

            try:
                event_start_datetime, event_end_datetime = get_dates(event_time)
            except Exception as e:
                logging.info(f"Rejecting record: {e}")
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
            country_code = ""

            if not online:
                try:
                    location_el = driver.find_element(
                        By.CSS_SELECTOR, "section.CardAddress--Location"
                    )
                except NoSuchElementException:
                    logging.info("Rejecting record: no location")
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
                description_el = driver.find_element(
                    By.CSS_SELECTOR, "div.CampaignHeader--Description"
                )
            except NoSuchElementException:
                logging.info(f"Rejecting record: no description")
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
                country_code,
                latitude,
                longitude,
                page.get("language_code"),
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
