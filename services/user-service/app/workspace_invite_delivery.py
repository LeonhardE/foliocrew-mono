"""Deliver an invitation through the configured, domain-scoped mail account."""

import http.client
import json
import os
import re

INVITATION_FROM = "Foliocrew <invites@foliocrew.app>"
INVITATION_LINK = "https://hub.foliocrew.app/"


class DeliveryUnconfirmed(Exception):
    """The provider did not confirm the delivery request."""


def send_invitation(email: str, delivery_key: str) -> str:
    key = os.environ.get("FOLIOCREW_INVITATION_MAIL_KEY")
    if not key:
        raise DeliveryUnconfirmed
    subject = "You’re invited to Foliocrew"
    text = "You’ve been invited to the Foliocrew workspace."
    link = INVITATION_LINK
    staging_origin = os.environ.get("FOLIOCREW_INVITATION_STAGING_ORIGIN")
    if staging_origin is not None:
        project = os.environ.get("FIREBASE_PROJECT_ID", "")
        if (
            not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project)
            or staging_origin != f"https://{project}.web.app"
        ):
            raise DeliveryUnconfirmed
        subject = "[Staging] " + subject
        text = "This is a test invitation to the Foliocrew staging workspace."
        link = staging_origin + "/"
    message = {
        "from": INVITATION_FROM,
        "to": [email],
        "subject": subject,
        "text": f"{text} Open {link} and sign in with the Google account that received this email.",
    }
    connection = http.client.HTTPSConnection("api.resend.com", timeout=8)
    try:
        connection.request(
            "POST",
            "/emails",
            json.dumps(message, ensure_ascii=True).encode(),
            {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Idempotency-Key": delivery_key,
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise DeliveryUnconfirmed
        raw = response.read(4097)
        if len(raw) > 4096:
            raise DeliveryUnconfirmed
        data = json.loads(raw)
        message_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(message_id, str) or not 1 <= len(message_id) <= 128:
            raise DeliveryUnconfirmed
        return message_id
    except (ValueError, OSError, http.client.HTTPException) as error:
        raise DeliveryUnconfirmed from error
    finally:
        connection.close()
