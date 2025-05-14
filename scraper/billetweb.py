import re
import json
import logging
from datetime import timedelta

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from db.records import get_record_dict
from utils.date_and_time import get_dates
from utils.errors import FreskError
from utils.keywords import *
from utils.language import detect_language_code_from_title_and_description
from utils.location import get_address


def get_billetweb_data(sources, service, options):
    logging.info("Scraping data from www.billetweb.fr")

    driver = webdriver.Firefox(service=service, options=options)
    wait = WebDriverWait(driver, 10)

    records = []

    for page in sources:
        logging.info(f"==================\nProcessing page {page}")
        driver.get(page["url"])

        try:
            wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, page["iframe"])))
        except TimeoutException:
            logging.info("Rejecting record: iframe not found")
            continue

        wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")
        ele = driver.find_elements(By.CSS_SELECTOR, "a.naviguate")
        links = [e.get_attribute("href") for e in ele]

        for link in links:
            logging.info(f"------------------\nProcessing event {link}")
            driver.get(link)
            wait.until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )

            # Useful for different workshops sharing same event link
            if "filter" in page:
                if page["filter"] not in link:
                    logging.info(
                        "Rejecting filter: expected filter keyword not present in current link"
                    )
                    continue

            # Description
            try:
                driver.find_element(By.ID, "more_info").click()
            except Exception:
                pass  # normal case if description is without more info

            try:
                description = driver.find_element(by=By.CSS_SELECTOR, value="#description").text
            except Exception:
                logging.info("Rejecting record: no description")
                continue

            # Parse event id
            event_id = re.search(r"/([^/]+?)&", link).group(1)
            if not event_id:
                logging.info("Rejecting record: event_id not found")
                continue

            # Parse main title
            try:
                main_title = driver.find_element(
                    by=By.CSS_SELECTOR, value="#event_title > div.event_name"
                ).text
            except NoSuchElementException:
                main_title = driver.find_element(
                    by=By.CSS_SELECTOR,
                    value="#description_block > div.event_title > div.event_name",
                ).text

            # Location data
            try:
                try:
                    main_full_location = driver.find_element(
                        by=By.CSS_SELECTOR, value="div.location_summary"
                    ).text
                except NoSuchElementException:
                    main_full_location = driver.find_element(
                        by=By.CSS_SELECTOR,
                        value="#page_block_location > div.location > div.location_info > div.address > a",
                    ).text
            except Exception:
                main_full_location = ""

            event_info = []

            # Retrieve sessions if exist
            wait.until(
                EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, "#shop_block iframe"))
            )
            wait.until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )
            back_links = driver.find_elements(By.CSS_SELECTOR, ".back_header_link.summarizable")
            if back_links:
                # Case of Multi-time with only one date, we arrive directly to Basket, so get back to sessions
                driver.get(back_links[0].get_attribute("href"))
                wait.until(
                    lambda driver: driver.execute_script("return document.readyState") == "complete"
                )
            sessions = driver.find_elements(By.CSS_SELECTOR, "a.sesssion_href")
            sessions_links = [
                s.get_attribute("href") for s in sessions
            ]  # No sessions for Mono-time
            driver.switch_to.parent_frame()

            ################################################################
            # Multi-time management
            ################################################################
            for sessions_link in sessions_links:
                driver.get(sessions_link)
                wait.until(
                    lambda driver: driver.execute_script("return document.readyState") == "complete"
                )
                context = driver.find_element(By.CSS_SELECTOR, "#context_title").text

                # Parse title, dates, location
                if match := re.match(
                    r"\s*((?P<title>.*) : )?(?P<event_time>.*)(\n\s*(?P<full_location>.*))?",
                    context,
                ):
                    if not match.group("title"):
                        sub_title = main_title
                    elif "atelier" in match.group("title").lower():
                        sub_title = match.group("title")
                    else:
                        sub_title = main_title + " - " + match.group("title")

                    event_time = match.group("event_time")
                    sub_full_location = (
                        match.group("full_location")
                        if match.group("full_location")
                        else main_full_location
                    )
                else:
                    raise

                # Is it full?
                try:
                    # The presence of div.block indicates that the event is sold out,
                    # except if the text below is displayed.
                    empty = driver.find_element(By.CSS_SELECTOR, "div.block")
                    sold_out = not has_external_tickets(empty.text)
                except NoSuchElementException:
                    sold_out = False

                # Parse session id
                session_id = re.search(r"&session=(\d+)", sessions_link).group(1)
                uuid = f"{event_id}-{session_id}"

                event_info.append(
                    [sub_title, event_time, sub_full_location, sold_out, sessions_link, uuid]
                )

            ################################################################
            # Mono-time management
            ################################################################
            if not sessions_links:
                # Parse start and end dates
                try:
                    event_time = driver.find_element(
                        by=By.CSS_SELECTOR,
                        value="#event_title > div.event_start_time > span.text",
                    ).text
                except NoSuchElementException:
                    event_time = driver.find_element(
                        by=By.CSS_SELECTOR,
                        value="#description_block > div.event_title > span > a > div.event_start_time",
                    ).text

                # Is it full?
                try:
                    wait.until(
                        EC.frame_to_be_available_and_switch_to_it(
                            (By.CSS_SELECTOR, "#shop_block iframe")
                        )
                    )
                    wait.until(
                        lambda driver: driver.execute_script("return document.readyState")
                        == "complete"
                    )

                    # The presence of div.block indicates that the event is sold out,
                    # except if the text below is displayed.
                    empty = driver.find_element(By.CSS_SELECTOR, "div.block")
                    sold_out = not has_external_tickets(empty.text)
                except NoSuchElementException:
                    sold_out = False
                finally:
                    driver.switch_to.parent_frame()

                event_info.append(
                    [main_title, event_time, main_full_location, sold_out, link, event_id]
                )

            ################################################################
            # Session loop
            ################################################################
            for index, (title, event_time, full_location, sold_out, ticket_link, uuid) in enumerate(
                event_info
            ):
                logging.info(
                    f"\n-> Processing session {index+1}/{len(event_info)} {ticket_link} ..."
                )
                if is_gift_card(title):
                    logging.info("Rejecting record: gift card")
                    continue

                ################################################################
                # Date and time
                ################################################################
                try:
                    event_start_datetime, event_end_datetime = get_dates(event_time)
                except Exception as e:
                    logging.info(f"Rejecting record: {e}")
                    continue

                if event_end_datetime - event_start_datetime > timedelta(days=1):
                    logging.info(f"Rejecting record: event is too long: {event_time}")
                    continue

                # Is it an online event?
                online = is_online(title) or is_online(full_location)
                title = title.replace(" Online event", "")  # Button added by billetweb

                ################################################################
                # Location data
                ################################################################
                location_name = address = city = department = longitude = latitude = zip_code = (
                    country_code
                ) = ""
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
                    page.get("language_code", detect_language_code_from_title_and_description(title, description)),
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

    driver.quit()

    return records
