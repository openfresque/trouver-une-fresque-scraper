import json
import requests
import logging
import pandas as pd

from datetime import datetime, timedelta

from db.records import get_record_dict
from utils.errors import FreskError
from utils.keywords import *
from utils.language import detect_language_code
from utils.location import get_address


def get_json_from_source(source):
    try:
        response = requests.get(source)
        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            return response.json()
        else:
            logging.info(f"Request failed with status code: {response.status_code}")
    except requests.RequestException as e:
        logging.info(f"An error occurred: {e}")


def get_mobilite_data(source):
    logging.info("Getting data from Fresque de la Mobilité API")

    records = []

    # Workaround to get two make results and merge them (will change in the future)
    json_sessions = get_json_from_source("https://hook.eu1.make.com/ui9bvl4c3w69dxdlb7goskl3o22x74um")
    df_sessions = pd.json_normalize(json_sessions["response"]["results"])
    json_versions = get_json_from_source("https://hook.eu1.make.com/sy4ud6vxutts9h62t4tt6gv0xr5rrkyd")
    df_versions = pd.json_normalize(json_versions["response"]["results"])
    df_sessions = df_sessions.merge(df_versions, how='left', left_on="atelier_version_custom_atelier_version", right_on="_id", suffixes=(None, "_y"))

    for event_id, row in df_sessions.iterrows():
        logging.info("")

        online = is_online(row["format_option_version_format"])
        training = is_training(row["type_option_version_type"])
        description = ""
        kids = is_for_kids(row["p_rim_tre_option_version_p_rim_tre"])
        sold_out = (row["nb_places_number"] - row["nb_participants_number"]) == 0
        source_link = tickets_link = f'https://app.fresquedelamobilite.org/atelier_details/{row["_id"]}'
        title = f'{row["type_option_version_type"]} {row["th_me_option_version_th_me"]} {row["p_rim_tre_option_version_p_rim_tre"]} {row["format_option_version_format"]}'

        ################################################################
        # Parse start and end dates
        ################################################################
        try:
            # Convert time strings to datetime objects
            event_start_datetime = datetime.strptime(row["date_date"], "%Y-%m-%dT%H:%M:%S.%fZ")
        except Exception as e:
            logging.info(f"Rejecting record: bad date format {e}")
            continue

        try:
            event_end_datetime = event_start_datetime + timedelta(minutes=row["dur_e__en_minutes__number"])
        except Exception as e:
            logging.info(f"Rejecting record: bad duration format {e}")
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
            try:
                address_dict = get_address(row["lieu_adresse_exact_text"])
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
            detect_language_code(title, description),
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
