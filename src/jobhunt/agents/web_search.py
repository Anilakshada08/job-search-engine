"""Web search agents: one LLM sub-agent per job site, run in parallel.

Each sub-agent uses the server-side web_search / web_fetch tools to find Angular postings on
its site within the date window, then a structured-output call turns its notes into postings.
Sites that block fetching are reported as unavailable, never worked around.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel

from ..models import JobPosting
from ..textutil import within_days
from .base import Agent, RunContext


class FoundJob(BaseModel):
    company: str
    title: str
    location: str
    job_type: str
    posted: str               # ISO date if known, else ""
    date_unclear: bool
    link: str
    job_id: str
    recruiter: str
    description: str          # key requirements, as written in the posting (max ~1500 chars)


class SiteResult(BaseModel):
    jobs: list[FoundJob]
    blocked: bool             # true if the site refused/blocked fetching
    blocked_reason: str


SEARCH_SYSTEM = """You are a job-search sub-agent for ONE job site. Find Angular developer postings
posted within the last {days} days that are Remote (United States) or in the Chicago metro
(within ~{radius} miles of {home}). Use the site's own past-{days}-days filter where it has one.
Keywords: {keywords}.
Open each promising posting and record: company (the real employer, and any end client named),
exact title, location/remote policy, job type, posted date, link, job ID, recruiter name if shown,
and the key required skills/years. If the site blocks fetching, stop and say so; do not try other
ways to get the page. Never sign in, never solve CAPTCHAs."""


class WebSearchAgent(Agent):
    name = "web_search"

    def run(self, ctx: RunContext) -> None:
        if ctx.llm is None:
            for s in ctx.config.settings.get("web_sites", []):
                ctx.site(s["name"]).unavailable = "LLM disabled (--no-llm)"
            return
        sites = ctx.config.settings.get("web_sites", [])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda s: (s, self._search_site(ctx, s)), sites))
        days = ctx.config.settings["window"]["posted_within_days"]
        for site, res in results:
            rep = ctx.site(site["name"])
            if isinstance(res, Exception):
                rep.unavailable = f"agent error: {res}"
                continue
            if res.blocked:
                rep.unavailable = res.blocked_reason or "blocked"
                continue
            rep.searched = True
            for j in res.jobs:
                fresh = within_days(j.posted, days)
                if fresh is False:
                    continue
                rep.found += 1
                ctx.postings.append(JobPosting(
                    company=j.company, title=j.title, location=j.location, job_type=j.job_type,
                    posted=j.posted, date_unclear=j.date_unclear or fresh is None, source=site["name"],
                    link=j.link, job_id=j.job_id, recruiter=j.recruiter, description=j.description))

    def _search_site(self, ctx: RunContext, site: dict):
        p = ctx.config.profile
        s = ctx.config.settings
        system = SEARCH_SYSTEM.format(
            days=s["window"]["posted_within_days"], radius=p.get("chicago_metro_radius_miles", 25),
            home=p.get("home_location", "Arlington Heights, IL"), keywords=", ".join(s["keywords"]))
        try:
            notes = ctx.llm.research(system=system, prompt=f"Site: {site['name']}\nHow to search it: {site['hints']}")
            return ctx.llm.structured(
                system="Convert these job-search notes into the schema. Only include postings the notes "
                       "actually describe; never invent fields (use empty strings when unknown).",
                prompt=notes, schema=SiteResult, role="worker")
        except Exception as e:  # isolate one site's failure from the others
            return e
