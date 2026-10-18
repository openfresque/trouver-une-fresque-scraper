import json
import requests
import time
import logging
import os
import urllib.parse

from datetime import datetime

from trouver_une_fresque_scraper.db.records import get_record_dict
from trouver_une_fresque_scraper.utils.errors import FreskError
from trouver_une_fresque_scraper.utils.keywords import *
from trouver_une_fresque_scraper.utils.language import detect_language_code
from trouver_une_fresque_scraper.utils.location import get_address
from trouver_une_fresque_scraper.apis.ics import get_ticketing_url_from_description


def get_gcal_data(source):
    records = []
    workshop_id = source["id"]

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        logging.info(
            f"API key to query Google Calendar is unavailable, skipping workshop ID {workshop_id}."
        )
        return records

    json_records = []
    try:
        print(datetime.now().isoformat(timespec="seconds"))
        params = urllib.parse.urlencode(
            {
                "calendarId": source["calendarId"],
                "timeMin": datetime.now().isoformat(timespec="seconds") + "Z",
                "key": api_key,
            }
        )
        url = source["url"] + "?" + params
        logging.info(f"Getting Google Calendar data from {url}")
        response = requests.get(url)
        if response.status_code == 200:
            json_records = response.json()
        else:
            logging.info(f"Request failed with status code: {response.status_code}")
    except requests.RequestException as e:
        logging.info(f"An error occurred: {e}")

    for record in json_records["items"]:

        ################################################################
        # Get event metadata
        ################################################################
        event_id = record["iCalUID"]
        title = record["summary"]
        online = False
        training = False
        sold_out = False
        kids = False
        source_link = record["htmlLink"]
        description = record["description"]

        ################################################################
        # Parse start and end dates
        ################################################################
        event_start_time = record["start"]["dateTime"]
        try:
            # Convert time strings to datetime objects
            event_start_datetime = datetime.fromisoformat(event_start_time)
        except Exception as e:
            logging.info(f"Rejecting record: bad date format {e}")
            continue

        event_end_time = record["end"]["dateTime"]
        try:
            # Convert time strings to datetime objects
            event_end_datetime = datetime.fromisoformat(event_end_time)
        except Exception as e:
            logging.info(f"Rejecting record: bad date format {e}")
            continue

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

        full_location = record["location"]
        if not full_location:
            logging.info("Rejecting record: no location provided")
            continue

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
        except json.JSONDecodeError:
            logging.info("Rejecting record: error while parsing API response")
            continue
        except FreskError as error:
            logging.info(f"Rejecting record: {error}.")
            continue

        ################################################################
        # Parse tickets link
        ################################################################
        tickets_link = get_ticketing_url_from_description(description)
        if not tickets_link:
            logging.warning(f"Rejecting record {workshop_id}: no ticket link extracted.")
            continue

        ################################################################
        # Building final object
        ################################################################
        record = get_record_dict(
            f"{workshop_id}-{event_id}",
            workshop_id,
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
            source.get("language_code", detect_language_code(title, description)),
            online,
            training,
            sold_out,
            kids,
            source_link,
            tickets_link,
            description,
        )

        records.append(record)
        logging.info(f"Extracted event\n{json.dumps(record, indent=4)}")

    return records
