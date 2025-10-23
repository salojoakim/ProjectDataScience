"""
Fetch recent messages from a Microsoft 365 shared mailbox and save them as .eml files.

Uses MSAL (client credentials) + Microsoft Graph:
- Lists messages from a folder (e.g., Inbox) within a date window (e.g., last N days).
- Downloads each message in MIME format to a local folder for the parser pipeline.

Requires:
- Azure App Registration with Graph Application permission "Mail.Read" and admin consent.
- Tenant ID, Client ID, Client Secret, shared mailbox address.

Keeps the core pipeline decoupled from Graph specifics.
"""


# utils/graph_mail.py
import os
import re
import time
import json
import shutil
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

import requests
from msal import ConfidentialClientApplication


GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _iso_utc_days_back(days_back: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_back)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _sanitize_filename(s: str) -> str:
    s = re.sub(r"[^\w\-.]+", "_", s.strip())
    return s[:180]  # försiktigt med path-limitar


def _get_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    app = ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
    )
    # Client credentials => scope ".default"
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"Failed to get token: {result}")
    return result["access_token"]


def _graph_get(url: str, token: str, params: Optional[Dict] = None) -> Dict:
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, params=params, timeout=60)
    if not resp.ok:
        raise RuntimeError(f"Graph GET {url} failed: {resp.status_code} {resp.text[:500]}")
    return resp.json()


def _graph_get_bytes(url: str, token: str) -> bytes:
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, timeout=120)
    if not resp.ok:
        raise RuntimeError(f"Graph GET bytes {url} failed: {resp.status_code} {resp.text[:500]}")
    return resp.content


def fetch_shared_mailbox_to_folder(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    shared_mailbox: str,
    dest_folder: str,
    days_back: int = 1,
    mail_folder: str = "Inbox",
    clear_dest_first: bool = True,
    top: int = 50,
) -> List[str]:
    """
    Hämtar meddelanden (senaste days_back dagar) från en shared mailbox till dest_folder som .eml-filer.
    Returnerar lista med sparade filvägar.
    * Kräver Application Permissions i Azure: Mail.Read (admin consent).
    """
    token = _get_token(tenant_id, client_id, client_secret)
    since_iso = _iso_utc_days_back(days_back)

    if clear_dest_first and os.path.isdir(dest_folder):
        shutil.rmtree(dest_folder, ignore_errors=True)
    os.makedirs(dest_folder, exist_ok=True)

    # 1) List messages med filter på tid
    #    Vi tar med subject, receivedDateTime. Body behövs ej här eftersom vi hämtar MIME ($value)
    url = f"{GRAPH_BASE}/users/{shared_mailbox}/mailFolders/{mail_folder}/messages"
    params = {
        "$select": "id,subject,receivedDateTime",
        "$filter": f"receivedDateTime ge {since_iso}",
        "$orderby": "receivedDateTime desc",
        "$top": top,
    }

    saved_files: List[str] = []

    while True:
        data = _graph_get(url, token, params=params)
        params = None  # endast första callen använder params

        for item in data.get("value", []):
            mid = item["id"]
            subject = item.get("subject") or "no_subject"
            received = item.get("receivedDateTime") or ""
            # 2) Hämta rå MIME (.eml)
            eml_bytes = _graph_get_bytes(f"{GRAPH_BASE}/users/{shared_mailbox}/messages/{mid}/$value", token)

            # 3) Spara till fil
            ts = received.replace(":", "").replace("-", "")
            fname = _sanitize_filename(f"{ts}_{subject}_{mid}.eml")
            fpath = os.path.join(dest_folder, fname)
            with open(fpath, "wb") as f:
                f.write(eml_bytes)
            saved_files.append(fpath)

        next_link = data.get("@odata.nextLink")
        if not next_link:
            break
        # Graph throttling safety
        time.sleep(0.4)
        url = next_link

    return saved_files
