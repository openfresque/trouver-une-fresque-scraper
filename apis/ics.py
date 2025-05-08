import csv
import datetime
import json
import pytz
import requests
import logging

from db.records import get_record_dict
from ics import Calendar
from utils.errors import FreskError
from utils.location import get_address


def get_ics_data(source):
    logging.info("Getting data from ICS file in iCalendar format")

    calendar = None
    records = []

    try:
        response = requests.get(source["url"])
        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            calendar = Calendar(response.text)
        else:
            logging.info(f"Request failed with status code: {response.status_code}")
    except requests.RequestException as e:
        logging.info(f"An error occurred: {e}")

    if not calendar:
        return records

    for event in calendar.events:

        ################################################################
        # Kick out event early if it is in the past
        ################################################################
        event_start_datetime = event.begin
        event_end_datetime = event.end
        if event_start_datetime < pytz.UTC.localize(datetime.datetime.now()):
            continue

        ################################################################
        # Get basic event metadata
        ################################################################
        event_id = event.uid
        title = event.name
        description = event.description

        ################################################################
        # Location data, or online
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

        online = event.location == None
        if not online:
            try:
                full_location = event.location
                address_dict = get_address(full_location.split("\n", 1).pop())
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
        # Infer more event metadata
        ################################################################
        title_upper = title.upper()
        training = "FORMATION" in title_upper or "TRAINING" in title_upper
        sold_out = False
        kids = False

        ################################################################
        # Get tickets link (more sophisticated parsing to be added later)
        ################################################################
        tickets_link = event.url
        source_link = tickets_link
        if not tickets_link:
            logging.info(f"Rejecting record {event_id}: no ticket link extracted.")
            continue

        ################################################################
        # Building final object
        ################################################################
        record = get_record_dict(
            f"{source['id']}-{event_id}",
            source["id"],
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
            online,
            training,
            sold_out,
            kids,
            source_link,
            tickets_link,
            description,
        )

        records.append(record)
        logging.info(f"Successfully got record\n{json.dumps(record, indent=4)}")

    logging.info(f"Got {len(records)} records.")
    return records
