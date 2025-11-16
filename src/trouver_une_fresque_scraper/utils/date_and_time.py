import re
import traceback

from datetime import datetime, timedelta
from dateutil.parser import parse

from trouver_une_fresque_scraper.utils.errors import (
    FreskError,
    FreskDateBadFormat,
    FreskDateDifferentTimezone,
)

DEFAULT_DURATION = 3
CURRENT_YEAR = 2025

FRENCH_SHORT_DAYS = {
    "lun": 1,
    "mar": 2,
    "mer": 3,
    "jeu": 4,
    "ven": 5,
    "sam": 6,
    "dim": 7,
}

FRENCH_DAYS = {
    "lundi": 1,
    "mardi": 2,
    "mercredi": 3,
    "jeudi": 4,
    "vendredi": 5,
    "samedi": 6,
    "dimanche": 7,
}

FRENCH_SHORT_MONTHS = {
    "janv": 1,
    "févr": 2,
    "mars": 3,
    "avr": 4,
    "mai": 5,
    "juin": 6,
    "juil": 7,
    "août": 8,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "déc": 12,
}

FRENCH_MONTHS = {
    "janvier": 1,
    "février": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
}


def get_dates(event_time):
    try:
        # ===================
        # FdC English

        # June 03, 2025, from 05:30pm to 09:30pm (Paris time)
        if match := re.match(
            r"(?P<date>\w+\s\d{2},\s\d{4})"
            r",\sfrom\s"
            r"(?P<start_time>\d{2}:\d{2}[ap]m)"
            r"\sto\s"
            r"(?P<end_time>\d{2}:\d{2}[ap]m)"
            r"\s\(.*\stime\)",
            event_time,
        ):
            event_start_datetime = parse(f"{match.group('date')} {match.group('start_time')}")
            event_end_datetime = parse(f"{match.group('date')} {match.group('end_time')}")
            return event_start_datetime, event_end_datetime

        # ===================
        # Billetweb

        # Thu Oct 19, 2023 from 01:00 PM to 02:00 PM
        if match := re.match(
            r"(?P<date>.*)\s" r"from\s" r"(?P<start_time>.*)\s" r"to\s" r"(?P<end_time>.*)",
            event_time,
        ):
            event_start_datetime = parse(f"{match.group('date')} {match.group('start_time')}")
            event_end_datetime = parse(f"{match.group('date')} {match.group('end_time')}")
            return event_start_datetime, event_end_datetime

        # ===================
        # Billetweb

        # Thu Oct 19, 2023 at 01:00 PM to Sat Feb 24, 2024 at 02:00 PM
        elif match := re.match(
            r"(?P<start_date>.*)\s"
            r"at\s"
            r"(?P<start_time>.*)\s"
            r"to\s"
            r"(?P<end_date>.*)\s"
            r"at\s"
            r"(?P<end_time>.*)",
            event_time,
        ):
            event_start_datetime = parse(f"{match.group('start_date')} {match.group('start_time')}")
            event_end_datetime = parse(f"{match.group('end_date')} {match.group('end_time')}")
            return event_start_datetime, event_end_datetime

        # ===================
        # Billetweb

        # Thu Oct 19, 2023 at 01:00 PM
        # March 7, 2025 at 10:00 AM
        elif match := re.match(r"(?P<date>.*)\s" r"at\s" r"(?P<time>.*)", event_time):
            event_start_datetime = parse(f"{match.group('date')} {match.group('time')}")
            event_end_datetime = event_start_datetime + timedelta(hours=DEFAULT_DURATION)
            return event_start_datetime, event_end_datetime

        # ===================
        # Eventbrite

        # ven. 11 avr. 2025 14:00 - 17:30 CEST
        elif match := re.match(
            rf"(?P<day_of_week>{'|'.join(FRENCH_SHORT_DAYS.keys())})\.?\s"
            r"(?P<day>\d{1,2})\s"
            rf"(?P<month>{'|'.join(FRENCH_SHORT_MONTHS.keys())})\.?\s"
            r"(?P<year>\d{4})\s"
            r"(?P<start_time>\d{2}:\d{2})\s"
            r"-\s"
            r"(?P<end_time>\d{2}:\d{2})\s"
            r"(?P<timezone>.*)",
            event_time,
        ):
            event_start_datetime = datetime(
                int(match.group("year")),
                FRENCH_SHORT_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("start_time").split(":")[0]),
                int(match.group("start_time").split(":")[1]),
            )
            event_end_datetime = datetime(
                int(match.group("year")),
                FRENCH_SHORT_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("end_time").split(":")[0]),
                int(match.group("end_time").split(":")[1]),
            )
            return event_start_datetime, event_end_datetime

        # ===================
        # FdC French

        # 16 mai 2025, de 18h30 à 21h30 (heure de Paris)
        elif match := re.match(
            r"(?P<day>\d{1,2})\s"
            rf"(?P<month>{'|'.join(FRENCH_MONTHS.keys())})\s"
            r"(?P<year>\d{4}),\s"
            r"de\s"
            r"(?P<start_time>\d{1,2}h\d{2})\s"
            r"à\s"
            r"(?P<end_time>\d{1,2}h\d{2})",
            event_time,
        ):
            # Construct the datetime objects
            event_start_datetime = datetime(
                int(match.group("year")),
                FRENCH_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("start_time").split("h")[0]),
                int(match.group("start_time").split("h")[1]),
            )
            event_end_datetime = datetime(
                int(match.group("year")),
                FRENCH_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("end_time").split("h")[0]),
                int(match.group("end_time").split("h")[1]),
            )
            return event_start_datetime, event_end_datetime

        # ===================
        # FEC

        # 03 mars 2025, 14:00 – 17:00 UTC+1
        elif match := re.match(
            rf"((?P<day_of_week>{'|'.join(FRENCH_SHORT_DAYS.keys())})\.?\s)?"
            r"(?P<day>\d{1,2})\s"
            rf"(?P<month>{'|'.join(FRENCH_SHORT_MONTHS.keys())})\.?\s"
            r"(?P<year>\d{4})?,\s"
            r"(?P<start_time>\d{2}:\d{2})\s"
            r"–\s"
            r"(?P<end_time>\d{2}:\d{2})"
            r"(\sUTC(?P<timezone>.*))?",
            event_time,
        ):
            timezone = match.group("timezone")
            if timezone and timezone not in ("+1", "+2"):
                raise FreskDateDifferentTimezone(event_time)

            event_start_datetime = datetime(
                int(match.group("year")),
                FRENCH_SHORT_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("start_time").split(":")[0]),
                int(match.group("start_time").split(":")[1]),
            )
            event_end_datetime = datetime(
                int(match.group("year")),
                FRENCH_SHORT_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("end_time").split(":")[0]),
                int(match.group("end_time").split(":")[1]),
            )
            return event_start_datetime, event_end_datetime

        # ===================
        # Glide

        # mercredi 12 février 2025 de 19h00 à 22h00
        elif match := re.match(
            rf"((?P<day_of_week>{'|'.join(FRENCH_DAYS.keys())})\s)?"
            r"(?P<day>\d{1,2})\s"
            rf"(?P<month>{'|'.join(FRENCH_MONTHS)})\s"
            r"(?P<year>\d{4})\s"
            r"de\s"
            r"(?P<start_time>\d{1,2}h\d{2})\s"
            r"à\s"
            r"(?P<end_time>\d{1,2}h\d{2})",
            event_time,
        ):
            event_start_datetime = datetime(
                int(match.group("year")),
                FRENCH_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("start_time").split("h")[0]),
                int(match.group("start_time").split("h")[1]),
            )
            event_end_datetime = datetime(
                int(match.group("year")),
                FRENCH_MONTHS[match.group("month")],
                int(match.group("day")),
                int(match.group("end_time").split("h")[0]),
                int(match.group("end_time").split("h")[1]),
            )
            return event_start_datetime, event_end_datetime

        # ===================
        # HelloAsso

        # Le 12 février 2025, de 18h à 20h
        elif match := re.match(
            r"Le\s"
            r"(?P<day>\d{1,2})\s"
            rf"(?P<month>{'|'.join(FRENCH_MONTHS)})\s"
            r"(?P<year>\d{4}),\s"
            r"de\s"
            r"(?P<start_time>\d{1,2}h\d{0,2})\s"
            r"à\s"
            r"(?P<end_time>\d{1,2}h\d{0,2})",
            event_time,
        ):
            start_parts = match.group("start_time").split("h")
            event_start_datetime = datetime(
                int(match.group("year")),
                FRENCH_MONTHS[match.group("month")],
                int(match.group("day")),
                int(start_parts[0]),
                (int(start_parts[1]) if len(start_parts) > 1 and len(start_parts[1]) else 0),
            )
            end_parts = match.group("end_time").split("h")
            event_end_datetime = datetime(
                int(match.group("year")),
                FRENCH_MONTHS[match.group("month")],
                int(match.group("day")),
                int(end_parts[0]),
                int(end_parts[1]) if len(end_parts) > 1 and len(end_parts[1]) else 0,
            )
            return event_start_datetime, event_end_datetime

        else:
            raise FreskDateBadFormat(event_time)

    except Exception as e:
        if not isinstance(e, FreskError):
            traceback.print_exc()
        raise FreskDateBadFormat(event_time)


def get_dates_from_element(el):
    """Returns start and end datetime objects extracted from the element.

    The "datetime" attribute of the element is used if present to extract the date, otherwise falls back on get_dates to parse the day and hours from the element text. Returns None, None on failure.

    May throw FreskDateDifferentTimezone, FreskDateBadFormat and any exception thrown by get_dates.
    """
    event_day = el.get_attribute("datetime")
    event_time = el.text

    # Leverage the datetime attribute if present.
    # datetime: 2025-12-05
    # text: déc. 5 de 9am à 12pm UTC+1
    if event_day:
        day_match = re.match(r"(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})", event_day)
        # TODO: add support for minutes not 0.
        # TODO: add proper support for timezone.
        # We use re.search to skip the text for the date at the beginning of the string.
        hour_match = re.search(
            r"de\s"
            r"(?P<start_time>\d{1,2})(?P<start_am_or_pm>[ap]m)\s"
            r"à\s"
            r"(?P<end_time>\d{1,2})(?P<end_am_or_pm>[ap]m)\s"
            r"(UTC(?P<timezone>.*))?",
            event_time,
        )
        if day_match and hour_match:
            timezone = hour_match.group("timezone")
            if timezone and timezone not in ("+1", "+2"):
                raise FreskDateDifferentTimezone(event_time)
            hour_offset = 12
            dt = datetime(
                int(day_match.group("year")),
                int(day_match.group("month")),
                int(day_match.group("day")),
            )
            return datetime(
                dt.year,
                dt.month,
                dt.day,
                int(hour_match.group("start_time"))
                + (12 if hour_match.group("start_am_or_pm") == "pm" else 0),
                0,
            ), datetime(
                dt.year,
                dt.month,
                dt.day,
                int(hour_match.group("end_time"))
                + (12 if hour_match.group("end_am_or_pm") == "pm" else 0),
                0,
            )

    return get_dates(event_time)
