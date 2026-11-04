import datetime

from pioneercd import radio


def at(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%H:%M")


def test_parse_now_and_next():
    data = {"channel": {
        "currentscheduledepisode": {"title": "Ekot", "starttimeutc": "/Date(1793782800000)/",
                                    "endtimeutc": "/Date(1793784600000)/"},
        "nextscheduledepisode": {"title": "Vetandets värld", "starttimeutc": "/Date(1793784600000)/"}}}
    assert radio.parse(data) == {"now": ("Ekot", f"{at(1793782800000)}–{at(1793784600000)}"),
                                 "next": ("Vetandets värld", at(1793784600000))}


def test_parse_nothing_scheduled():
    assert radio.parse({"channel": {}}) == {}
