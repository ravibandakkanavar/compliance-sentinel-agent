import smtplib
from email.message import EmailMessage

import config
import db


def send_campaign(subject, body):
    sent = 0
    with smtplib.SMTP(config.SMTP_HOST) as smtp:
        smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        for user in db.all_active_users():
            message = EmailMessage()
            message["To"] = user["email"]
            message["From"] = config.SMTP_USER
            message["Subject"] = subject
            message.set_content(body.replace("{name}", user["full_name"]))
            smtp.send_message(message)
            sent += 1
    return sent
