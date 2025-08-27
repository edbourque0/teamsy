import time
import math
import logging
from os import getenv
from typing import Iterable, List
from dotenv import load_dotenv

import requests
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import TenantUser, PresenceCurrent, PresenceSnapshot

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

# Tune these as needed
GROUP_PAGE_SIZE = 100            # Graph default paging is fine; we just follow @odata.nextLink
PRESENCE_BATCH_SIZE = 100        # Graph getPresencesByUserId max is 100 ids/request
MAX_RETRIES = 4                  # for 429/5xx
INITIAL_BACKOFF_SEC = 2.0

def _get_token() -> str:
    """Client credentials flow using your existing requests-based approach."""
    tenant_id = getenv("TENANT_ID")
    r = requests.post(
        TOKEN_URL.format(tenant_id=tenant_id),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": getenv("CLIENT_ID"),
            "client_secret": getenv("CLIENT_SECRET"),
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _graph_get(url: str, token: str, params: dict | None = None) -> dict:
    """GET with simple retry/backoff for 429/5xx and return JSON."""
    backoff = INITIAL_BACKOFF_SEC
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params or {},
            timeout=30,
        )
        if resp.status_code in (429, 500, 502, 503, 504):
            retry_after = resp.headers.get("Retry-After")
            sleep_s = float(retry_after) if retry_after else backoff
            log.warning("Graph GET %s throttled (%s). Sleeping %.1fs (attempt %d/%d).",
                        url, resp.status_code, sleep_s, attempt, MAX_RETRIES)
            time.sleep(sleep_s)
            backoff *= 2
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()  # last error


def _graph_post_json(url: str, token: str, payload: dict) -> dict:
    """POST JSON with retry/backoff and return JSON."""
    backoff = INITIAL_BACKOFF_SEC
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        if resp.status_code in (429, 500, 502, 503, 504):
            retry_after = resp.headers.get("Retry-After")
            sleep_s = float(retry_after) if retry_after else backoff
            log.warning("Graph POST %s throttled (%s). Sleeping %.1fs (attempt %d/%d).",
                        url, resp.status_code, sleep_s, attempt, MAX_RETRIES)
            time.sleep(sleep_s)
            backoff *= 2
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()  # last error


def _iter_group_members(group_id: str, token: str) -> Iterable[dict]:
    """
    Yield all members of a group. Each item is a user or directory object.
    We use $select to keep payloads lean.
    """
    url = f"{GRAPH_BASE}/groups/{group_id}/members"
    params = {"$select": "id,displayName,mail"}
    while True:
        data = _graph_get(url, token, params=params)
        for item in data.get("value", []):
            yield item
        next_link = data.get("@odata.nextLink")
        if not next_link:
            break
        url, params = next_link, None  # nextLink already includes the params


def _chunk(lst: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


@shared_task(name="teamspresenceapp.tasks.poll_presence")
def poll_presence():
    """
    Periodic task (every 5 min) to:
      1) Resolve members of GROUP_ID
      2) Fetch their presence in batches (getPresencesByUserId)
      3) Upsert TenantUser & PresenceCurrent, and append PresenceSnapshot
    """
    load_dotenv()
    group_id = getenv("GROUP_ID")
    if not group_id:
        log.error("GROUP_ID is not set; aborting poll.")
        return

    started = timezone.now()
    token = _get_token()

    # 1) Resolve members and upsert TenantUser
    member_ids: list[str] = []
    seen_user_ids: set[str] = set()

    created_users = 0
    updated_users = 0

    for m in _iter_group_members(group_id, token):
        # Only handle user objects (some groups can contain service principals, etc.)
        uid = m.get("id")
        if not uid:
            continue
        display_name = m.get("displayName") or ""
        email = m.get("mail")

        with transaction.atomic():
            obj, created = TenantUser.objects.select_for_update().get_or_create(
                aad_user_id=uid,
                defaults={"display_name": display_name[:255], "email": email, "is_active": True},
            )
            if created:
                created_users += 1
            else:
                # Update if changed; keep writes minimal
                fields_to_update = []
                if display_name and obj.display_name != display_name:
                    obj.display_name = display_name[:255]
                    fields_to_update.append("display_name")
                if email != obj.email:
                    obj.email = email
                    fields_to_update.append("email")
                if not obj.is_active:
                    obj.is_active = True
                    fields_to_update.append("is_active")
                if fields_to_update:
                    obj.save(update_fields=fields_to_update)
                    updated_users += 1

        seen_user_ids.add(uid)
        member_ids.append(uid)

    # Optionally mark users that disappeared from the group as inactive
    TenantUser.objects.exclude(aad_user_id__in=seen_user_ids).filter(is_active=True).update(is_active=False)

    # 2) Fetch presence in batches
    total = len(member_ids)
    if total == 0:
        log.info("Group %s has no members. Done.", group_id)
        return

    now = timezone.now()
    processed = 0
    snapshots_to_create: list[PresenceSnapshot] = []

    for batch_ids in _chunk(member_ids, PRESENCE_BATCH_SIZE):
        payload = {"ids": batch_ids}
        data = _graph_post_json(f"{GRAPH_BASE}/communications/getPresencesByUserId", token, payload)

        for item in data.get("value", []):
            uid = item.get("id")
            availability = item.get("availability") or "PresenceUnknown"
            activity = item.get("activity") or "PresenceUnknown"

            try:
                user = TenantUser.objects.get(aad_user_id=uid)
            except TenantUser.DoesNotExist:
                # Shouldn't happen, but guard anyway
                continue

            # Upsert current presence (update only if changed)
            with transaction.atomic():
                curr, created = PresenceCurrent.objects.select_for_update().get_or_create(
                    user=user,
                    defaults={
                        "availability": availability,
                        "activity": activity,
                        "fetched_at": now,
                    },
                )
                if not created:
                    if curr.availability != availability or curr.activity != activity or curr.fetched_at < now:
                        curr.availability = availability
                        curr.activity = activity
                        curr.fetched_at = now
                        curr.save(update_fields=["availability", "activity", "fetched_at", "updated_at"])

            # Queue snapshot (append-only)
            snapshots_to_create.append(
                PresenceSnapshot(
                    user=user,
                    availability=availability,
                    activity=activity,
                    fetched_at=now,
                )
            )

            processed += 1

    # 3) Bulk insert snapshots (efficient)
    if snapshots_to_create:
        PresenceSnapshot.objects.bulk_create(snapshots_to_create, batch_size=1000, ignore_conflicts=False)

    duration = (timezone.now() - started).total_seconds()
    log.info("Presence poll complete: users=%d (created=%d, updated=%d), presences=%d, duration=%.2fs",
             total, created_users, updated_users, processed, duration)
