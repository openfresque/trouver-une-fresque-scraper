import csv
import datetime
import json
import pytz
import re
import requests
import logging

from db.records import get_record_dict
from ics import Calendar
import re
from utils.errors import FreskError
from utils.language import detect_language_code
from utils.location import get_address
import xml.etree.ElementTree as ET


# from https://regexr.com/37i6s
REGEX_URL = "https?:\\/\\/(?:www\\.)?[-a-zA-Z0-9@:%._\\+~#=]{1,256}\\.[a-zA-Z0-9()]{1,6}\\b(?:[-a-zA-Z0-9()@:%_\\+.~#?&\\/=]*)"

IGNORABLE_DOMAINS = [
    "https://meet.google.com",
    "https://support.google.com",
    "https://us02web.zoom.us",
]

TICKETING_TEXT = ["registration", "ticket", "inscription"]


# Returns a ticketing URL extracted from a description in plain text or formatted as HTML.
def get_ticketing_url_from_description(description):
    # list of tuples: (URL, anchor text if HTML document otherwise same URL)
    links = []

    try:
        # try as HTML document
        root = ET.fromstring(description)
        for elem in root.findall(".//a[@href]"):
            links.append((elem.get("href"), elem.text))
    except ET.ParseError:
        # fall back to plain text
        for url in re.findall(REGEX_URL, description):
            links.append((url, url))

    def should_link_be_kept(link):
        url = link[0]
        for domain in IGNORABLE_DOMAINS:
            if url.startswith(domain):
                return False
        return True

    links = list(filter(should_link_be_kept, links))
    if len(links) == 1:
        return links[0][0]

    def does_text_look_like_registration(link):
        lower_text = link[1].upper()
        for text in TICKETING_TEXT:
            if lower_text.find(text) > -1:
                return True
        return False

    links = list(filter(does_text_look_like_registration, links))
    if len(links) == 1:
        return links[0][0]

    return None


def get_ics_data(source):
    logging.info(f"Getting iCalendar data from {source['url']}")

    calendar = None
    records = []

    try:
        response = requests.get(source["url"])
        # Check if the request was successful (status code 200).
        if response.status_code == 200:
            # Remove VALARMs which incorrectly crash the ics library.
            text = re.sub("BEGIN:VALARM.*END:VALARM", "", response.text, flags=re.DOTALL)
            calendar = Calendar(text)
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
        # Get tickets link: try URL else extract from description
        ################################################################
        tickets_link = event.url
        if not tickets_link and event.description:
            tickets_link = get_ticketing_url_from_description(event.description)
        if not tickets_link:
            logging.warning(f"Rejecting record {event_id}: no ticket link extracted.")
            continue
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
            source.get(
                "language_code", detect_language_code(title, description)
            ),
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
