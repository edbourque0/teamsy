import os
from datetime import datetime

import msal
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from .database import SessionLocal
from . import models

TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["https://graph.microsoft.com/.default"]

scheduler = BackgroundScheduler()


def acquire_token():
    app = msal.ConfidentialClientApplication(
        CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET
    )
    result = app.acquire_token_silent(SCOPE, account=None)
    if not result:
        result = app.acquire_token_for_client(scopes=SCOPE)
    if "access_token" in result:
        return result["access_token"]
    raise RuntimeError("Could not acquire access token")


def fetch_presence(access_token: str):
    headers = {"Authorization": f"Bearer {access_token}"}
    users_resp = requests.get(
        "https://graph.microsoft.com/v1.0/users?$select=id,displayName", headers=headers
    )
    users_resp.raise_for_status()
    users = users_resp.json().get("value", [])

    for user in users:
        presence_resp = requests.get(
            f"https://graph.microsoft.com/v1.0/users/{user['id']}/presence",
            headers=headers,
        )
        presence_resp.raise_for_status()
        presence = presence_resp.json()
        store_presence(user["id"], user.get("displayName"), presence)


def store_presence(user_id: str, display_name: str, presence: dict):
    db: Session = SessionLocal()
    try:
        record = models.PresenceRecord(
            user_id=user_id,
            display_name=display_name,
            availability=presence.get("availability"),
            activity=presence.get("activity"),
            collected_at=datetime.utcnow().replace(minute=0, second=0, microsecond=0),
        )
        db.add(record)
        db.commit()
    finally:
        db.close()


def update_presence():
    try:
        token = acquire_token()
        fetch_presence(token)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to update presence: {exc}")


def start_scheduler():
    scheduler.add_job(update_presence, "interval", hours=1, next_run_time=datetime.utcnow())
    scheduler.start()
