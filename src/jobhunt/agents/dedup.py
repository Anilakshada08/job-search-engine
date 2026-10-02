"""De-duplication agent (deterministic).

Phase "pre":  collapse cross-site copies of the same job and drop anything on the do-not-repeat list
              (link/job-ID match, or same company + near-identical title on any site).
Phase "post": after screening has extracted end clients, drop staffing reposts of a handled
              end-client role.
"""
from __future__ import annotations

from ..models import JobPosting, SkippedJob
from ..textutil import job_ids, same_company, title_similarity
from .base import Agent, DoNotRepeatEntry, RunContext

TITLE_MATCH = 0.85
SOURCE_PRIORITY = ["greenhouse", "lever", "ashby", "workable", "smartrecruiters", "breezy", "jazzhr",
                   "company ats boards", "linkedin", "dice", "built in", "wellfound", "simplyhired",
                   "himalayas", "remoteok", "jobicy", "arc.dev"]


def _priority(source: str) -> int:
    s = source.lower()
    for i, name in enumerate(SOURCE_PRIORITY):
        if s.startswith(name):
            return i
    return len(SOURCE_PRIORITY)


def same_job(a_company: str, a_title: str, b_company: str, b_title: str) -> bool:
    return same_company(a_company, b_company) and title_similarity(a_title, b_title) >= TITLE_MATCH


def match_history(p: JobPosting, history: list[DoNotRepeatEntry], end_client: str = "") -> DoNotRepeatEntry | None:
    ids = job_ids(p.link)
    for h in history:
        if h.link and ids & job_ids(h.link):
            return h
        if same_job(p.company, p.title, h.company, h.title):
            return h
        if end_client and same_job(end_client, p.title, h.company, h.title):
            return h
    return None


class DedupAgent(Agent):
    name = "dedup"

    def __init__(self, phase: str = "pre") -> None:
        super().__init__()
        self.phase = phase

    def run(self, ctx: RunContext) -> None:
        if self.phase == "pre":
            ctx.postings = self._against_history(ctx, self._collapse(ctx.postings))
        else:
            kept = []
            for p, s in ctx.candidates:
                h = match_history(p, ctx.do_not_repeat, s.end_client) if s.end_client else None
                if h:
                    ctx.skipped.append(self._skip(p, h))
                else:
                    kept.append((p, s))
            ctx.candidates = kept

    @staticmethod
    def _collapse(postings: list[JobPosting]) -> list[JobPosting]:
        groups: list[list[JobPosting]] = []
        for p in sorted(postings, key=lambda x: _priority(x.source)):
            for g in groups:
                if (job_ids(p.link) & job_ids(g[0].link)) or same_job(p.company, p.title, g[0].company, g[0].title):
                    g.append(p)
                    break
            else:
                groups.append([p])
        out = []
        for g in groups:
            keep = g[0]
            keep.other_sites = sorted({x.source for x in g[1:] if x.source != keep.source})
            if keep.date_unclear and any(not x.date_unclear for x in g[1:]):
                dated = next(x for x in g[1:] if not x.date_unclear)
                keep.posted, keep.date_unclear = dated.posted, False
            out.append(keep)
        return out

    def _against_history(self, ctx: RunContext, postings: list[JobPosting]) -> list[JobPosting]:
        kept = []
        for p in postings:
            stay = next((r for r in ctx.reevaluated_skips if same_company(p.company, r.get("company", ""))), None)
            if stay:
                ctx.skipped.append(SkippedJob(company=p.company, title=p.title, source=p.source,
                                              link=p.link, reason=f"Stays skipped: {stay.get('reason', '')}"))
                continue
            h = match_history(p, ctx.do_not_repeat)
            if h:
                ctx.skipped.append(self._skip(p, h))
            else:
                kept.append(p)
        return kept

    @staticmethod
    def _skip(p: JobPosting, h: DoNotRepeatEntry) -> SkippedJob:
        if h.status.startswith("Skipped earlier"):
            return SkippedJob(company=p.company, title=p.title, source=p.source, link=p.link, reason=h.status)
        when = h.date or "earlier run"
        return SkippedJob(company=p.company, title=p.title, source=p.source, link=p.link,
                          reason=f"Skipped - already handled ({when})", already_handled=True)
