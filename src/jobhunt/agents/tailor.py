"""Tailor agent: scores each screened job and writes a truthful ATS resume for 70%+ matches.

Truthfulness guard (code, not prompt): every experience entry must keep the base resume's
employer, client, title and dates; skills must come from the profile; anything else is dropped
and reported. Match % = JD keywords that actually appear in the rendered PDF / all JD keywords.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from ..llm import dumps
from ..models import ExperienceEntry, JobPosting, PreparedJob, Screening, SkippedJob, TailoredResume
from ..resume import render
from ..textutil import file_safe
from .base import Agent, RunContext

TAILOR_SYSTEM = """You tailor an ATS resume for one job, using ONLY the candidate's base resume (JSON).
Steps:
1. Extract the JD keywords: required/preferred skills, tools, years, domain, soft skills, and phrases
   repeated 2+ times. Keep each keyword short (1-4 words), as written in the JD.
2. For each keyword: if the candidate has it, put it on the resume truthfully (mirror the JD wording
   when the base resume uses a synonym); if she does not have it, do NOT add it - list it in gap_keywords.
3. headline = the job's exact title. summary = 3-4 lines, Angular first. skills = Angular and the JD's
   Angular-related keywords first, then secondary keywords; every skill must be in the base resume.
4. experience: every role from the base resume, in the same order, with company, client, title and
   dates copied EXACTLY; rewrite bullets as action + tech + result in JD phrasing, most relevant first,
   never inventing metrics, tools, employers, titles, degrees or certifications. Keep it to 2 pages
   (about 3-5 bullets for recent roles, 1-2 for older ones).
5. matched_keywords = JD keywords present on your resume. match_percent = round(100 * matched /
   (matched + gaps)). Years: the candidate has 7 years of Angular/JavaScript/TypeScript; a JD asking
   for more is a gap, never inflate.
6. risk = one short line on the main risk (e.g. "asks 10+ years", "contract via staffing agency").

WRITING STYLE: it must read like the candidate wrote it, not like generated text.
- Plain verbs (built, fixed, set up, moved, wrote, cut). Never: spearheaded, leveraged, orchestrated,
  seamless, robust, synergy, cutting-edge, dynamic, passionate, results-driven, "proven track record".
- No em dashes. No bold or "label: description" bullets. No three-adjective lists.
- Vary bullet length and shape: some short, some with a concrete detail (app name, team size, what
  changed). Don't start every bullet with the same pattern or end every bullet with a result clause.
- Keep the specifics from the base resume (ERAS, NIFAIS, Capital One, team sizes, 95% coverage).
- Mirror at most a handful of the JD's exact phrases where they are true; never paste a list of JD
  keywords into the summary. Summary: 2-4 plain sentences, no slogans."""


class Tailored(TailoredResume):
    risk: str


ACCOUNT_DOMAINS = ("myworkdayjobs", "icims", "taleo", "successfactors", "oraclecloud", "brassring", "ultipro")
NO_ACCOUNT_DOMAINS = ("greenhouse", "lever.co", "ashbyhq", "workable", "breezy", "smartrecruiters", "applytojob")


def apply_route(link: str) -> tuple[str, bool | None]:
    host = urlparse(link).netloc.lower()
    if "linkedin" in host:
        return "LinkedIn", None
    if any(d in host for d in ACCOUNT_DOMAINS):
        return f"Company ATS ({host})", True
    if any(d in host for d in NO_ACCOUNT_DOMAINS):
        return f"Company ATS ({host})", False
    return host or "unknown", None


def enforce_truth(t: Tailored, profile: dict) -> list[str]:
    """Mutates t to match the base resume; returns notes about anything removed."""
    notes = []
    base = profile["experience"]
    fixed = []
    for i, src in enumerate(base):
        got = t.experience[i] if i < len(t.experience) else None
        entry = ExperienceEntry(
            title=src["title"], company=src["company"], client=src.get("client", ""), dates=src["dates"],
            tech=[x for x in (got.tech if got else src.get("tech", [])) if _known(x, profile)] or src.get("tech", []),
            bullets=(got.bullets if got and got.bullets else src["bullets"]))
        if got and (got.company != src["company"] or got.dates != src["dates"] or got.title != src["title"]):
            notes.append(f"restored employer/title/dates for role {i + 1}")
        fixed.append(entry)
    t.experience = fixed
    kept = [s for s in t.skills if _known(s, profile)]
    if len(kept) != len(t.skills):
        notes.append("dropped skills not in base resume: " + ", ".join(sorted(set(t.skills) - set(kept))))
    t.skills = kept
    t.education = list(profile["education"])
    return notes


def _profile_text(profile: dict) -> str:
    parts = profile.get("primary_skills", []) + profile.get("secondary_skills", []) + profile.get("domains", [])
    for e in profile["experience"]:
        parts += e.get("tech", []) + e.get("bullets", [])
    return " ".join(parts).lower()


def _known(skill: str, profile: dict) -> bool:
    hay = _profile_text(profile)
    s = skill.lower().strip()
    if s in hay:
        return True
    # tolerate formatting differences ("NgRx Store" vs "NgRx (Store/Effects)")
    words = [w for w in re.findall(r"[a-z0-9.+#/]+", s) if len(w) > 1]
    return bool(words) and all(w in hay for w in words)


class TailorAgent(Agent):
    name = "tailor"

    def run(self, ctx: RunContext) -> None:
        if ctx.llm is None:
            for p, _ in ctx.candidates:
                ctx.skipped.append(SkippedJob(company=p.company, title=p.title, source=p.source, link=p.link,
                                              reason="Not screened or scored (--no-llm run)"))
            return
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda c: (c, self._tailor(ctx, *c)), ctx.candidates))
        for (p, s), res in results:
            if isinstance(res, Exception):
                ctx.errors.append(f"tailoring failed for {p.key}: {res}")
            elif res.match_percent >= ctx.config.settings["thresholds"]["ready"]:
                ctx.prepared.append(res)
            elif res.match_percent >= ctx.config.settings["thresholds"]["fyi"]:
                ctx.fyi.append(res)
            else:
                ctx.skipped.append(SkippedJob(company=p.company, title=p.title, source=p.source, link=p.link,
                                              reason=f"Low match ({res.match_percent}%)"))
            if not isinstance(res, Exception):
                ctx.gaps += res.gap_keywords[:3]

    def _tailor(self, ctx: RunContext, p: JobPosting, s: Screening):
        try:
            profile = ctx.config.profile
            base = {k: profile[k] for k in ("headline", "primary_skills", "secondary_skills", "domains",
                                            "experience", "education")}
            t = ctx.llm.structured(system=TAILOR_SYSTEM + "\n\nBASE RESUME:\n" + dumps(base),
                                   prompt=dumps(p.model_dump()), schema=Tailored)
            t.headline = p.title  # exact JD title, always
            notes = enforce_truth(t, profile)
            via, needs_account = apply_route(p.link)
            job = PreparedJob(posting=p, screening=s, match_percent=t.match_percent,
                              matched_keywords=t.matched_keywords, gap_keywords=t.gap_keywords,
                              risk="; ".join(filter(None, [t.risk] + notes)), apply_via=via,
                              needs_account=needs_account)
            if t.match_percent < ctx.config.settings["thresholds"]["ready"]:
                return job
            self._render(ctx, p, t, job)
            return job
        except Exception as e:
            return e

    def _render(self, ctx: RunContext, p: JobPosting, t: Tailored, job: PreparedJob) -> None:
        profile = ctx.config.profile
        stem = f"{file_safe(profile['name'].split()[0])}_{file_safe(profile['name'].split()[-1])}_" \
               f"{file_safe(p.company)}_{file_safe(p.title)}"
        out = ctx.config.output_dir / ctx.started.astimezone().strftime("%Y-%m-%d")
        out.mkdir(parents=True, exist_ok=True)
        docx, pdf, att = out / f"{stem}.docx", out / f"{stem}.pdf", out / "attach" / f"{stem}.pdf"
        att.parent.mkdir(exist_ok=True)

        # Keep within 2 pages: trim bullets from the oldest roles first.
        for _ in range(12):
            render.render_pdf(t, profile, pdf)
            if render.pdf_pages(pdf) <= 2:
                break
            for e in reversed(t.experience):
                if len(e.bullets) > 1:
                    e.bullets.pop()
                    break
            else:
                break
        render.render_docx(t, profile, docx)
        # Prefer a Word-exported PDF: clean ATS text layer and ordinary metadata. Keep the
        # ReportLab PDF when Word isn't available or its export runs past 2 pages.
        word_pdf = pdf.with_suffix(".word.pdf")
        if render.export_pdf_with_word(docx, word_pdf) and render.pdf_pages(word_pdf) <= 2:
            word_pdf.replace(pdf)
        else:
            word_pdf.unlink(missing_ok=True)
        render.render_attachment_pdf(t, profile, att)

        missing = render.verify_keywords(pdf, t.matched_keywords)
        matched = [k for k in t.matched_keywords if k not in missing]
        total = len(t.matched_keywords) + len(t.gap_keywords)
        job.match_percent = round(100 * len(matched) / total) if total else 0
        job.matched_keywords, job.missing_on_pdf = matched, missing
        job.resume_docx, job.resume_pdf, job.attachment_pdf = str(docx), str(pdf), str(att)
        # Upgraded to "Ready to submit (stopped at Review)" only when chrome-applier confirms it.
        job.status = "Ready - Akshada applies"
