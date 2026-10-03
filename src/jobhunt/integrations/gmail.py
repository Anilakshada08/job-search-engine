"""Gmail API access: read earlier run summaries and send the run email."""
from __future__ import annotations

import base64
import os
import re
from email.message import EmailMessage
from html import unescape
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


class Gmail:
    def __init__(self) -> None:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds_file = Path(os.environ.get("GMAIL_CREDENTIALS_FILE", "credentials.json"))
        token_file = Path(os.environ.get("GMAIL_TOKEN_FILE", "token.json"))
        creds = None
        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # One-time interactive consent; scheduled runs reuse the saved token.
                flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
                creds = flow.run_local_server(port=0)
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(creds.to_json(), encoding="utf-8")
        self.svc = build("gmail", "v1", credentials=creds, cache_discovery=False)

    # -- read ------------------------------------------------------------
    def search_threads(self, query: str) -> list[str]:
        ids, token = [], None
        while True:
            res = self.svc.users().threads().list(userId="me", q=query, pageToken=token).execute()
            ids += [t["id"] for t in res.get("threads", [])]
            token = res.get("nextPageToken")
            if not token:
                return ids

    def thread_text(self, thread_id: str) -> str:
        th = self.svc.users().threads().get(userId="me", id=thread_id, format="full").execute()
        parts = []
        for msg in th.get("messages", []):
            headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            parts.append(f"Subject: {headers.get('subject', '')}\nDate: {headers.get('date', '')}")
            parts.append(_payload_text(msg["payload"]))
        return "\n".join(parts)

    # -- send ------------------------------------------------------------
    def send(self, to: str, subject: str, html: str, text: str, attachments: list[Path]) -> str:
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        for p in attachments:
            msg.add_attachment(p.read_bytes(), maintype="application", subtype="pdf", filename=p.name)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        res = self.svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return res["id"]


def _payload_text(payload: dict) -> str:
    mime = payload.get("mimeType", "")
    data = payload.get("body", {}).get("data")
    if data and mime in ("text/plain", "text/html"):
        txt = base64.urlsafe_b64decode(data).decode("utf-8", "replace")
        return _strip_html(txt) if mime == "text/html" else txt
    subs = payload.get("parts", [])
    plain = [p for p in subs if p.get("mimeType") == "text/plain"]
    chosen = plain or subs
    return "\n".join(_payload_text(p) for p in chosen)


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", html)
    return unescape(re.sub(r"<[^>]+>", " ", html))
