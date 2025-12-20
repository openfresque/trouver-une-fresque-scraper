def is_training(input_string):
    training_list = [
        "formation",
        "briefing",
        "animateur",
        "animation",
        "permanence",
        "training",
        "return of experience",
        "retex",
    ]
    input_string = input_string.lower()
    return any(word.lower() in input_string for word in training_list)


def is_online(input_string):
    online_list = ["online", "en ligne", "distanciel", "en linea"]
    input_string = input_string.lower()
    return any(word.lower() in input_string for word in online_list)


def is_for_kids(input_string):
    kids_list = ["kids", "junior", "jeunes"]
    input_string = input_string.lower()
    return any(word.lower() in input_string for word in kids_list)


def has_external_tickets(input_string):
    external_tickets = [
        "inscriptions uniquement",
        "inscription uniquement",
        "inscriptions via",
        "inscription via",
    ]
    input_string = input_string.lower()
    return any(word.lower() in input_string for word in external_tickets)


def is_plenary(input_string):
    plenary = ["plénière"]
    input_string = input_string.lower()
    return any(word.lower() in input_string for word in plenary)


def is_sold_out(input_string):
    sold_out = ["complet"]
    input_string = input_string.lower()
    return any(word.lower() in input_string for word in sold_out)


def is_gift_card(input_string):
    gift = ["cadeau", "don"]
    input_string = input_string.lower()
    return any(word.lower() in input_string for word in gift)


def is_canceled(input_string):
    canceled = ["annulé"]
    input_string = input_string.lower()
    return any(word.lower() in input_string for word in canceled)
