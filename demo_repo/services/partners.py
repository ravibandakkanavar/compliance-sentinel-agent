import requests

import config
import db


def sync_audience():
    """Nightly job: share the customer audience with the advertising partner for a fee."""
    audience = [
        {
            "email": user["email"],
            "name": user["full_name"],
            "income_band": user["annual_income"] // 25000,
        }
        for user in db.all_active_users()
    ]
    response = requests.post(config.PARTNER_FEED_URL, json={"audience": audience}, timeout=30)
    response.raise_for_status()
    return len(audience)
