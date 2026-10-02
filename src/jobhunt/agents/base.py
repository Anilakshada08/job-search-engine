"""Agent base class and the shared run context (the 'blackboard' agents read and write)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..config import Config
from ..llm import LLM
from ..models import JobPosting, Mode, PreparedJob, SiteReport, SkippedJob


@dataclass
class DoNotRepeatEntry:
    company: str
    title: str
    link: str = ""
    date: str = ""
    status: str = ""
    source: str = ""          # where we learned about it: gmail / dashboard / seed / applied-list


@dataclass
class RunContext:
    config: Config
    llm: LLM | None
    started: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    mode: Mode = Mode.CLOUD
    linkedin_status: str = "Chrome not reachable"
    do_not_repeat: list[DoNotRepeatEntry] = field(default_factory=list)
    reevaluated_skips: list[dict] = field(default_factory=list)
    dashboard_data: dict | None = None
    postings: list[JobPosting] = field(default_factory=list)
    candidates: list[tuple] = field(default_factory=list)       # (JobPosting, Screening) after screening
    prepared: list[PreparedJob] = field(default_factory=list)   # >= ready threshold
    fyi: list[PreparedJob] = field(default_factory=list)        # fyi..ready-1
    skipped: list[SkippedJob] = field(default_factory=list)
    sites: dict[str, SiteReport] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    dashboard_line: str = "Dashboard: not updated - run did not reach the dashboard step"
    github_line: str = "GitHub page: not updated - run did not reach the publish step"
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    def site(self, name: str) -> SiteReport:
        return self.sites.setdefault(name, SiteReport(site=name))

    @property
    def date_str(self) -> str:
        return self.started.astimezone().strftime("%b %d, %Y")


class Agent:
    """One specialist. Agents communicate only through the RunContext."""

    name = "agent"

    def __init__(self) -> None:
        self.log = logging.getLogger(f"jobhunt.{self.name}")

    def run(self, ctx: RunContext) -> None:  # pragma: no cover - interface
        raise NotImplementedError
