"""Screener agent: applies the job criteria to each de-duplicated posting.

Hard rules (excluded employers, clearance, citizenship) run first in code so they can never be
argued away by a posting; judgement calls (Angular-primary, location, React-first, Java/.NET-primary)
go to an LLM with structured output.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from ..llm import dumps
from ..models import Decision, JobPosting, Screening, SkippedJob
from .base import Agent, RunContext

CLEARANCE_RE = re.compile(
    r"\b(security clearance|active clearance|clearance required|ts/sci|top secret|secret clearance|"
    r"public trust clearance|polygraph)\b", re.I)
CITIZEN_RE = re.compile(
    r"\b(u\.?s\.? citizens? only|must be a u\.?s\.? citizen|us citizenship (is )?required|"
    r"citizenship required|only (u\.?s\.?|us) citizens)\b", re.I)

COMMON_WORD_BRANDS = {"discover", "frog"}

SCREEN_SYSTEM = """You screen job postings for a Senior Angular developer. Keep a posting only if ALL hold:
1. Angular-primary: "Angular" is in the title, OR Angular is the first/main required framework.
   Skip React-first roles, "Angular, React or Vue" equal-option roles, generic UI/JS roles without
   Angular as main framework, Java/.NET/Python-primary full-stack roles, UX-designer and mobile roles.
2. Location: Remote (United States, not restricted to other states) OR Chicago metro (within ~{radius}
   miles of {home}; onsite/hybrid fine there). Skip hybrid/onsite elsewhere.
3. Full-time or contract (W2/C2C/1099).
4. Not clearance-required, not US-citizen-only (candidate holds a Green Card).
5. Not an excluded employer, and the JD body does not name one as employer, end client, vendor or
   partner. Excluded: {excluded}.
6. Not paywalled or scam-looking.
Return decision, a short reason (e.g. "React-first", "Hybrid in Dallas, TX", "Java back end primary"),
the end client if the JD names one, and gap_tags for why it fails or what it lacks, reusing these
phrases where they fit: "Java / .NET back end as main skill", "React-first or React/Angular equal",
"US citizenship / clearance", "8-10+ years required", "Onsite/hybrid outside Illinois"."""


class ScreenerAgent(Agent):
    name = "screener"

    def run(self, ctx: RunContext) -> None:
        excluded = [e.lower() for e in ctx.config.profile.get("excluded_employers", [])]
        survivors: list[JobPosting] = []
        for p in ctx.postings:
            reason = self._hard_rule(p, excluded)
            if reason:
                ctx.skipped.append(SkippedJob(company=p.company, title=p.title, source=p.source,
                                              link=p.link, reason=reason))
                ctx.gaps.append("US citizenship / clearance" if "clearance" in reason or "citizen" in reason
                                else "Excluded employer")
            else:
                survivors.append(p)

        if ctx.llm is None:
            ctx.candidates = [(p, Screening(decision=Decision.KEEP, reason="unscreened (--no-llm)",
                                            angular_primary=True, location_ok=True)) for p in survivors]
            return

        p = ctx.config.profile
        system = SCREEN_SYSTEM.format(radius=p.get("chicago_metro_radius_miles", 25),
                                      home=p.get("home_location", ""),
                                      excluded=", ".join(p.get("excluded_employers", [])))
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda j: (j, self._screen(ctx, system, j)), survivors))
        for job, res in results:
            if isinstance(res, Exception):
                ctx.errors.append(f"screening failed for {job.key}: {res}")
                continue
            ctx.gaps += res.gap_tags
            if res.decision == Decision.KEEP and not res.excluded_employer and not res.clearance_or_citizenship:
                ctx.candidates.append((job, res))
                ctx.site(job.source).kept += 1
            else:
                ctx.skipped.append(SkippedJob(company=job.company, title=job.title, source=job.source,
                                              link=job.link, reason=res.reason))

    @staticmethod
    def _hard_rule(p: JobPosting, excluded: list[str]) -> str:
        hay = f"{p.company}\n{p.title}\n{p.description}".lower()
        for name in excluded:
            # Common English words ("discover", "frog") only count in the company field; the LLM
            # screen still checks the JD body for them as a named client or vendor.
            where = p.company.lower() if name in COMMON_WORD_BRANDS else hay
            if re.search(rf"\b{re.escape(name)}\b", where):
                return f"Excluded employer/client ({name})"
        if CLEARANCE_RE.search(hay):
            return "Clearance required"
        if CITIZEN_RE.search(hay):
            return "US citizens only"
        return ""

    @staticmethod
    def _screen(ctx: RunContext, system: str, job: JobPosting):
        try:
            return ctx.llm.structured(system=system, prompt=dumps(job.model_dump()), schema=Screening)
        except Exception as e:
            return e
