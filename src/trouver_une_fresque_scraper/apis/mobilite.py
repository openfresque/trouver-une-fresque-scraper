import json
import requests
import logging
import pandas as pd

from datetime import datetime, timedelta

from trouver_une_fresque_scraper.db.records import get_record_dict
from trouver_une_fresque_scraper.utils.errors import FreskError
from trouver_une_fresque_scraper.utils.keywords import is_online, is_training, is_for_kids
from trouver_une_fresque_scraper.utils.language import detect_language_code
from trouver_une_fresque_scraper.utils.location import get_address


def get_df(source):
    try:
        response = requests.get(source)
        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            try:
                return pd.json_normalize(response.json()["response"]["results"])
            except KeyError as e:
                logging.info(f"incorrect results key in source json: {e}")
        else:
            logging.info(f"request failed with status code: {response.status_code}")
    except requests.RequestException as e:
        logging.info(f"request error occurred: {e}")


def get_mobilite_data(source):
    logging.info("Getting data from Fresque de la Mobilité API")

    records = []

    # Get two make results and merge them
    df_sessions = get_df("https://hook.eu1.make.com/ui9bvl4c3w69dxdlb7goskl3o22x74um")
    df_versions = get_df("https://hook.eu1.make.com/sy4ud6vxutts9h62t4tt6gv0xr5rrkyd")
    try:
        df_sessions = df_sessions.merge(
            df_versions,
            how="left",
            left_on="atelier_version_custom_atelier_version",
            right_on="_id",
            suffixes=(None, "_y"),
        )
    except Exception as e:
        logging.info(f"dataframe merge error occurred: {e}")
        return

    for event_id, row in df_sessions.iterrows():
        logging.info("")

        try:
            format_key = row["format_option_version_format"]
            type_key = row["type_option_version_type"]
            perimetre_key = row["p_rim_tre_option_version_p_rim_tre"]
            places_key = row["nb_places_number"]
            participants_key = row["nb_participants_number"]
            id_key = row["_id"]
            theme_key = row["th_me_option_version_th_me"]
            date_key = row["date_date"]
            duration_key = row["dur_e__en_minutes__number"]
            address_key = row["lieu_adresse_exact_text"]
        except KeyError as e:
            logging.info(f"incorrect key in source json: {e}")
            continue

        title = f"{type_key} {theme_key} {perimetre_key} {format_key}"
        description = ""
        online = is_online(format_key)
        sold_out = (places_key - participants_key) == 0
        source_link = tickets_link = f"https://app.fresquedelamobilite.org/atelier_details/{id_key}"

        ################################################################
        # Parse start and end dates
        ################################################################
        try:
            # Convert time strings to datetime objects
            event_start_datetime = datetime.strptime(date_key, "%Y-%m-%dT%H:%M:%S.%fZ")
        except Exception as e:
            logging.info(f"Rejecting record: bad date format {e}")
            continue

        try:
            event_end_datetime = event_start_datetime + timedelta(minutes=duration_key)
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
                address_dict = get_address(address_key)
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
            is_training(type_key),
            sold_out,
            is_for_kids(perimetre_key),
            source_link,
            tickets_link,
            description,
        )

        records.append(record)
        logging.info(f"Successfully API record\n{json.dumps(record, indent=4)}")

    return records
