"""Deterministic text helpers for de-duplication and slugs."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime

_COMPANY_SUFFIXES = re.compile(
    r"\b(inc|llc|l\.l\.c|ltd|corp|corporation|co|company|technologies|technology|tech|solutions|"
    r"group|holdings|plc|pvt|private|limited|usa|us|america)\b\.?",
    re.I,
)
_SENIORITY = {"sr": "senior", "jr": "junior", "snr": "senior", "lead": "lead"}
_TITLE_NOISE = re.compile(r"\b(remote|hybrid|onsite|on-site|contract|full[- ]time|w2|c2c|1099|usa?|us)\b", re.I)


def norm_company(name: str) -> str:
    s = _COMPANY_SUFFIXES.sub(" ", name.lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def norm_title(title: str) -> str:
    s = _TITLE_NOISE.sub(" ", title.lower())
    s = re.sub(r"\(.*?\)", " ", s)
    s = s.replace("front-end", "frontend").replace("front end", "frontend")
    words = [_SENIORITY.get(w, w) for w in re.findall(r"[a-z0-9.+#]+", s)]
    return " ".join(w.strip(".") for w in words if w.strip("."))


def title_similarity(a: str, b: str) -> float:
    na, nb = norm_title(a), norm_title(b)
    if not na or not nb:
        return 0.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    jaccard = len(ta & tb) / len(ta | tb)
    return max(ratio, jaccard)


def same_company(a: str, b: str) -> bool:
    na, nb = norm_company(a), norm_company(b)
    if not na or not nb:
        return False
    return na == nb or na.startswith(nb + " ") or nb.startswith(na + " ") or \
        SequenceMatcher(None, na, nb).ratio() >= 0.9


def job_ids(link: str) -> set[str]:
    """Stable identifiers inside a job URL (LinkedIn view IDs, ATS GUIDs, numeric IDs)."""
    ids = set()
    if not link:
        return ids
    m = re.search(r"linkedin\.com/jobs/view/(?:[^/]*?-)?(\d{8,})", link)
    if m:
        ids.add(f"li:{m.group(1)}")
    m = re.search(r"currentJobId=(\d{8,})", link)
    if m:
        ids.add(f"li:{m.group(1)}")
    for g in re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", link.lower()):
        ids.add(f"uuid:{g}")
    ids.add("url:" + re.sub(r"[?#].*$", "", link.lower()).rstrip("/").removeprefix("https://").removeprefix("http://").removeprefix("www."))
    return ids


def slug(*parts: str) -> str:
    s = "-".join(p for p in parts if p)
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80]


def file_safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:60]


def parse_date(value: str | int | float | None) -> date | None:
    """Parse ISO dates, epoch seconds/millis and relative phrases like '3 days ago'."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        ts = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(ts, tz=timezone.utc).date()
    v = str(value).strip().lower()
    today = datetime.now(timezone.utc).date()
    if v in ("today", "just posted", "new"):
        return today
    if v == "yesterday":
        return today - timedelta(days=1)
    m = re.match(r"(\d+)\+?\s*(minute|hour|day|week|month)s?\s+ago", v)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = {"minute": 0, "hour": 0, "day": n, "week": 7 * n, "month": 30 * n}[unit]
        return today - timedelta(days=days)
    if v.isdigit():
        return parse_date(int(v))
    raw = str(value).strip()
    try:
        return datetime.fromisoformat(re.sub(r"Z$", "+00:00", raw)).date()
    except ValueError:
        pass
    try:  # RFC 2822, as used by RSS-style feeds
        return parsedate_to_datetime(raw).date()
    except (TypeError, ValueError):
        return None


def within_days(posted: str | None, days: int) -> bool | None:
    d = parse_date(posted)
    if d is None:
        return None
    return (datetime.now(timezone.utc).date() - d).days <= days
