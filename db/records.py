import pandas as pd

from zoneinfo import ZoneInfo
from utils.utils import get_config


def get_record_dict(
    uuid,
    ids,
    title,
    start_datetime,
    end_datetime,
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
    event_link,
    tickets_link,
    description,
):
    timezone = get_config("timezone")
    origin_tz = ZoneInfo(timezone)

    return {
        "id": uuid,
        "workshop_type": ids,
        "title": title,
        "start_date": start_datetime.replace(tzinfo=origin_tz).isoformat(),
        "end_date": end_datetime.replace(tzinfo=origin_tz).isoformat(),
        "full_location": full_location,
        "location_name": location_name.strip(),
        "address": address.strip(),
        "city": city.strip(),
        "department": department,
        "zip_code": zip_code,
        "country_code": country_code,
        "latitude": latitude,
        "longitude": longitude,
        "language_code": (
            language_code.strip() if bool(language_code and language_code.strip()) else "fr"
        ),
        "online": online,
        "training": training,
        "sold_out": sold_out,
        "kids": kids,
        "source_link": event_link,
        "tickets_link": tickets_link,
        "description": description,
        "scrape_date": pd.to_datetime("now", utc=True).tz_convert(timezone).isoformat(),
    }
