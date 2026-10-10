import requests

import config


def track(event, user, ip_address):
    payload = {
        "event": event,
        "write_key": config.ANALYTICS_WRITE_KEY,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["full_name"],
            "date_of_birth": user["date_of_birth"],
            "ip": ip_address,
        },
    }
    requests.post(config.ANALYTICS_ENDPOINT, json=payload, timeout=5)
