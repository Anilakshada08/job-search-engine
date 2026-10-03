"""Feed search agent: polls public JSON job feeds directly (no LLM needed).

Covers Workable, RemoteOK, Jobicy, Himalayas and any configured Greenhouse / Lever / Ashby boards.
Only Angular-mentioning postings inside the date window are passed on; screening happens later.
"""
from __future__ import annotations

import re
from html import unescape

import httpx

from ..models import JobPosting
from ..textutil import parse_date, within_days
from .base import Agent, RunContext

UA = {"User-Agent": "jobhunt/0.1 (personal job search; contact via repository owner)"}


def _clean(html: str | None) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", html or "")).strip()


def _iso(value) -> str:
    """Feeds mix ISO strings and epoch seconds/millis; normalise to YYYY-MM-DD ('' if unknown)."""
    d = parse_date(value)
    return d.isoformat() if d else ""


def _angular(*texts: str) -> bool:
    return any("angular" in (t or "").lower() for t in texts)


class FeedSearchAgent(Agent):
    name = "feeds"

    def run(self, ctx: RunContext) -> None:
        feeds = ctx.config.settings.get("feeds", {})
        days = ctx.config.settings["window"]["posted_within_days"]
        with httpx.Client(headers=UA, timeout=30, follow_redirects=True) as http:
            for name, fn in (("Workable", self._workable), ("RemoteOK", self._remoteok),
                             ("Jobicy", self._jobicy), ("Himalayas", self._himalayas)):
                cfg = feeds.get(name.lower(), {})
                if cfg.get("enabled"):
                    self._collect(ctx, name, lambda: fn(http, cfg["url"]), days)
            for board in feeds.get("greenhouse_boards", []):
                self._collect(ctx, f"Greenhouse:{board}", lambda b=board: self._greenhouse(http, b), days)
            for board in feeds.get("lever_boards", []):
                self._collect(ctx, f"Lever:{board}", lambda b=board: self._lever(http, b), days)
            for board in feeds.get("ashby_boards", []):
                self._collect(ctx, f"Ashby:{board}", lambda b=board: self._ashby(http, b), days)

    def _collect(self, ctx: RunContext, site: str, fetch, days: int) -> None:
        rep = ctx.site(site)
        try:
            jobs = fetch()
        except httpx.HTTPStatusError as e:
            rep.unavailable = f"HTTP {e.response.status_code}"
            return
        except httpx.HTTPError as e:
            rep.unavailable = f"unreachable ({type(e).__name__})"
            return
        except Exception as e:  # malformed feed: report it, keep the other feeds going
            rep.unavailable = f"unexpected feed format ({type(e).__name__})"
            self.log.warning("%s feed failed: %s", site, e)
            return
        rep.searched = True
        for j in jobs:
            if not _angular(j.title, j.description):
                continue
            fresh = within_days(j.posted, days)
            if fresh is False:
                continue
            if fresh is None:
                j.date_unclear = True
            rep.found += 1
            ctx.postings.append(j)

    # -- individual feeds -----------------------------------------------
    def _workable(self, http: httpx.Client, url: str) -> list[JobPosting]:
        data = http.get(url).raise_for_status().json()
        out = []
        for j in data.get("jobs", []):
            loc = j.get("location") or {}
            out.append(JobPosting(
                company=(j.get("company") or {}).get("title", ""), title=j.get("title", ""),
                location=", ".join(filter(None, [loc.get("city"), loc.get("subregion"), loc.get("countryName")]))
                + (" (Remote)" if j.get("workplace") == "remote" else ""),
                job_type=j.get("employmentType", ""), posted=_iso(j.get("created", "")),
                source="Workable", link=j.get("url", ""), job_id=str(j.get("id", "")),
                description=_clean(j.get("description"))[:6000]))
        return out

    def _remoteok(self, http: httpx.Client, url: str) -> list[JobPosting]:
        data = http.get(url).raise_for_status().json()
        return [JobPosting(
            company=j.get("company", ""), title=j.get("position", ""), location=j.get("location") or "Remote",
            posted=_iso(j.get("date", "")), source="RemoteOK", link=j.get("url", ""), job_id=str(j.get("id", "")),
            description=_clean(j.get("description"))[:6000]) for j in data if isinstance(j, dict) and j.get("id")]

    def _jobicy(self, http: httpx.Client, url: str) -> list[JobPosting]:
        data = http.get(url).raise_for_status().json()
        return [JobPosting(
            company=j.get("companyName", ""), title=j.get("jobTitle", ""), location=j.get("jobGeo", "Remote"),
            job_type=", ".join(j.get("jobType") or []), posted=_iso(j.get("pubDate", "")), source="Jobicy",
            link=j.get("url", ""), job_id=str(j.get("id", "")),
            description=_clean(j.get("jobDescription"))[:6000]) for j in data.get("jobs", [])]

    def _himalayas(self, http: httpx.Client, url: str) -> list[JobPosting]:
        data = http.get(url).raise_for_status().json()
        return [JobPosting(
            company=j.get("companyName", ""), title=j.get("title", ""),
            location="Remote (" + ", ".join(j.get("locationRestrictions") or ["Worldwide"]) + ")",
            job_type=j.get("employmentType", ""), posted=_iso(j.get("pubDate", "")), source="Himalayas",
            link=j.get("applicationLink") or j.get("guid", ""), job_id=str(j.get("guid", "")),
            description=_clean(j.get("description"))[:6000]) for j in data.get("jobs", [])]

    def _greenhouse(self, http: httpx.Client, board: str) -> list[JobPosting]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
        data = http.get(url).raise_for_status().json()
        return [JobPosting(
            company=board, title=j.get("title", ""), location=(j.get("location") or {}).get("name", ""),
            posted=_iso(j.get("updated_at", "")), source="Greenhouse", link=j.get("absolute_url", ""),
            job_id=str(j.get("id", "")), description=_clean(unescape(j.get("content", "")))[:6000])
            for j in data.get("jobs", [])]

    def _lever(self, http: httpx.Client, board: str) -> list[JobPosting]:
        data = http.get(f"https://api.lever.co/v0/postings/{board}?mode=json").raise_for_status().json()
        return [JobPosting(
            company=board, title=j.get("text", ""), location=(j.get("categories") or {}).get("location", ""),
            job_type=(j.get("categories") or {}).get("commitment", ""), posted=_iso(j.get("createdAt", "")),
            source="Lever", link=j.get("hostedUrl", ""), job_id=j.get("id", ""),
            description=(j.get("descriptionPlain") or "")[:6000]) for j in data]

    def _ashby(self, http: httpx.Client, board: str) -> list[JobPosting]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
        data = http.get(url).raise_for_status().json()
        return [JobPosting(
            company=board, title=j.get("title", ""), location=j.get("location", "")
            + (" (Remote)" if j.get("isRemote") else ""), job_type=j.get("employmentType", ""),
            posted=_iso(j.get("publishedAt", "")), source="Ashby", link=j.get("jobUrl", ""), job_id=j.get("id", ""),
            description=(j.get("descriptionPlain") or "")[:6000]) for j in data.get("jobs", [])]
