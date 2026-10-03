"""Shared data models passed between agents."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Mode(str, Enum):
    CHROME = "CHROME MODE"
    CLOUD = "CLOUD MODE"


class JobPosting(BaseModel):
    """A raw posting as found by a search agent."""

    company: str
    title: str
    location: str = ""
    job_type: str = ""                # Full-time / Contract / ...
    posted: str = ""                  # ISO date, or "" when unknown
    date_unclear: bool = False
    source: str                       # site it was found on
    link: str
    job_id: str = ""
    description: str = ""             # JD text (may be truncated)
    recruiter: str = ""
    other_sites: list[str] = Field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.company} | {self.title}"


class Decision(str, Enum):
    KEEP = "keep"
    SKIP = "skip"


class Screening(BaseModel):
    """Output of the screener agent for one posting."""

    decision: Decision
    reason: str                       # short human reason, used in the email skip list
    angular_primary: bool
    location_ok: bool
    end_client: str = ""              # end client named in the JD (for de-dup and exclusions)
    excluded_employer: bool = False
    clearance_or_citizenship: bool = False
    gap_tags: list[str] = Field(default_factory=list)


class SkippedJob(BaseModel):
    company: str
    title: str
    source: str
    reason: str
    link: str = ""
    already_handled: bool = False


class ExperienceEntry(BaseModel):
    title: str
    company: str
    client: str
    dates: str
    tech: list[str]
    bullets: list[str]


class TailoredResume(BaseModel):
    headline: str                     # the job's exact title
    summary: str
    skills: list[str]
    experience: list[ExperienceEntry]
    education: list[str]
    matched_keywords: list[str]
    gap_keywords: list[str]
    match_percent: int


class PreparedJob(BaseModel):
    """A job that passed screening and was scored/tailored."""

    posting: JobPosting
    screening: Screening
    match_percent: int
    matched_keywords: list[str] = Field(default_factory=list)
    gap_keywords: list[str] = Field(default_factory=list)
    status: str = ""                  # "Ready - Akshada applies" | "Ready to submit (stopped at Review)" | ...
    apply_via: str = ""
    needs_account: Optional[bool] = None
    risk: str = ""
    resume_docx: str = ""
    resume_pdf: str = ""
    attachment_pdf: str = ""
    missing_on_pdf: list[str] = Field(default_factory=list)   # keyword verification failures


class SiteReport(BaseModel):
    site: str
    searched: bool = False
    found: int = 0
    kept: int = 0
    unavailable: str = ""
