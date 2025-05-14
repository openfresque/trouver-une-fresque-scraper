import json
import requests
import time
import logging

from datetime import datetime

from db.records import get_record_dict
from utils.errors import FreskError
from utils.keywords import *
from utils.location import get_address


def get_glorieuses_data(source):
    logging.info("Getting data from Glorieuses API")

    json_records = []
    records = []

    try:
        response = requests.get(source["url"])
        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            json_records = response.json()
        else:
            logging.info(f"Request failed with status code: {response.status_code}")
    except requests.RequestException as e:
        logging.info(f"An error occurred: {e}")

    for json_record in json_records:
        time.sleep(1.5)
        logging.info("")

        ################################################################
        # Get event id
        ################################################################
        event_id = json_record["RECORD_ID()"]

        ################################################################
        # Get event title
        ################################################################
        title = json_record["Label event"]

        ################################################################
        # Parse start and end dates
        ################################################################
        event_start_time = json_record["Date"]

        try:
            # Convert time strings to datetime objects
            event_start_datetime = datetime.strptime(event_start_time, "%Y-%m-%dT%H:%M:%S.%fZ")
        except Exception as e:
            logging.info(f"Rejecting record: bad date format {e}")
            continue

        event_end_time = json_record["Date fin"]

        try:
            # Convert time strings to datetime objects
            event_end_datetime = datetime.strptime(event_end_time, "%Y-%m-%dT%H:%M:%S.%fZ")
        except Exception as e:
            logging.info(f"Rejecting record: bad date format {e}")
            continue

        ###########################################################
        # Is it an online event?
        ################################################################
        if "Format" in json_record and json_record["Format"] is not None:
            online = is_online(json_record["Format"])
        else:
            logging.info(f"Rejecting record: no workshop format provided")
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

        if not online:
            address = json_record["Adresse"]
            if not address:
                logging.info("Rejecting record: no address provided")
                continue

            city = json_record["Ville"]
            full_location = f"{address}, {city}"

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
        # Description
        ################################################################
        description = json_record["Label event"]

        ################################################################
        # Training?
        ################################################################
        training = is_training(json_record["Type"])

        ################################################################
        # Is it full?
        ################################################################
        sold_out = False

        ################################################################
        # Is it suited for kids?
        ################################################################
        kids = False

        ################################################################
        # Parse tickets link
        ################################################################
        tickets_link = json_record["Lien billeterie"]
        source_link = tickets_link

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
            source.get("language_code"),
            online,
            training,
            sold_out,
            kids,
            source_link,
            tickets_link,
            description,
        )

        records.append(record)
        logging.info(f"Successfully API record\n{json.dumps(record, indent=4)}")

    return records
