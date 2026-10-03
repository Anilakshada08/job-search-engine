"""Safe read/append/write of the dashboard's embedded tracker JSON.

The dashboard HTML carries its data in
``<script type="application/json" id="tracker-data">{...}</script>``.
Rules: never remove jobs, never change an existing job's status, only append.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

TRACKER_RE = re.compile(
    r'(<script\b(?=[^>]*\bid="tracker-data")(?=[^>]*type="application/json")[^>]*>)(.*?)(</script>)',
    re.S,
)
NEW_JOB_FIELDS = ("id", "company", "role", "location", "type", "status", "match", "found",
                  "source", "applyVia", "link", "resume", "risk", "notes")
ALLOWED_STATUSES = {"Ready", "Needs Akshada", "Applied"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_tracker(html: str) -> dict:
    m = TRACKER_RE.search(html)
    if not m:
        raise ValueError('no <script type="application/json" id="tracker-data"> block found')
    data = json.loads(m.group(2))
    for key in ("jobs", "runs"):
        data.setdefault(key, [])
    return data


def serialize(data: dict) -> str:
    # chr(92) + "u003c" == "<": no literal "<" may remain inside the script tag.
    return json.dumps(data, indent=1).replace("<", chr(92) + "u003c")


def write_tracker(html: str, data: dict) -> str:
    m = TRACKER_RE.search(html)
    if not m:
        raise ValueError("tracker-data block disappeared")
    body = m.group(2)
    lead = body[: len(body) - len(body.lstrip())]
    trail = body[len(body.rstrip()):]
    return html[: m.start(2)] + lead + serialize(data) + trail + html[m.end(2):]


def append(data: dict, new_jobs: list[dict], run_record: dict) -> tuple[dict, list[str]]:
    """Append jobs (skipping ids/links already present) and one run record.

    Returns the new data and the list of job ids actually added.
    """
    existing_ids = {j.get("id") for j in data["jobs"]}
    existing_links = {j.get("link") for j in data["jobs"] if j.get("link")}
    added = []
    for job in new_jobs:
        job = {k: job.get(k, "") for k in NEW_JOB_FIELDS}
        if job["status"] not in ALLOWED_STATUSES:
            raise ValueError(f"invalid status {job['status']!r} for {job['id']}")
        if job["link"] and job["link"] in existing_links:
            continue
        base, n = job["id"], 2
        while job["id"] in existing_ids:
            job["id"] = f"{base}-{n}"
            n += 1
        data["jobs"].append(job)
        existing_ids.add(job["id"])
        added.append(job["id"])
    record = dict(run_record)
    record["ready"] = len(added)
    data["runs"].append(record)
    data["updated"] = utc_now_iso()
    return data, added


def update_file(html_path, new_jobs: list[dict], run_record: dict) -> list[str]:
    from pathlib import Path

    p = Path(html_path)
    html = p.read_text(encoding="utf-8")
    data, added = append(read_tracker(html), new_jobs, run_record)
    p.write_text(write_tracker(html, data), encoding="utf-8", newline="")
    return added
