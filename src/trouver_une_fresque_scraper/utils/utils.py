import json


def get_config(key=None):
    file = open("config.json", "r")
    file = json.loads(file.read())
    credentials = dict(file)
    if key is not None:
        return credentials.get(key, None)
    return credentials
