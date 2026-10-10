import os

DEBUG = True

SECRET_KEY = "shoplite-prod-7f3a9c2e41d8"
DATABASE_PATH = os.environ.get("SHOPLITE_DB", "shoplite.db")

SMTP_HOST = "smtp.shoplite.example"
SMTP_USER = "mailer@shoplite.example"
SMTP_PASSWORD = "Sh0pl1te!Mail2023"

ANALYTICS_ENDPOINT = "http://collect.trackwise.example/v1/events"
ANALYTICS_WRITE_KEY = os.environ.get("TRACKWISE_KEY", "")

PARTNER_FEED_URL = "https://partners.adreach.example/audiences"

# Number of days to keep order history and access logs. None keeps them indefinitely.
RETENTION_DAYS = None
