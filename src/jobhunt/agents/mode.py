"""Mode agent (step 0) and Chrome hand-off.

The Python engine has no browser. Browser work (LinkedIn sign-in check, site "Applied" lists,
LinkedIn search, filling applications up to the Review page) is done by the Claude Code
``chrome-scout`` and ``chrome-applier`` subagents, which hand their results over as JSON:

chrome_state.json   (written by chrome-scout before the prepare stage)
  {"reachable": true, "linkedin_profile": "Akshada Vaidya",
   "applied": [{"company": "...", "title": "...", "link": "...", "date": "YYYY-MM-DD", "site": "LinkedIn"}],
   "postings": [ <JobPosting fields> ... ], "signed_in_sites": ["Indeed"]}

chrome_results.json (written by chrome-applier before the report stage)
  {"<job link>": {"outcome": "review_reached" | "already_applied" | "needs_account" | "needs_answer" | "error",
                  "detail": "..."}}
"""
from __future__ import annotations

import json
from pathlib import Path

from ..models import JobPosting, Mode, SkippedJob
from .base import Agent, DoNotRepeatEntry, RunContext


def _load(path: str | None) -> dict | None:
    if not path or not Path(path).exists():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


class ModeAgent(Agent):
    name = "mode"

    def __init__(self, chrome_state: str | None = None) -> None:
        super().__init__()
        self.chrome_state = chrome_state

    def run(self, ctx: RunContext) -> None:
        state = _load(self.chrome_state)
        if not state or not state.get("reachable"):
            ctx.mode, ctx.linkedin_status = Mode.CLOUD, "Chrome not reachable"
            return
        candidate = ctx.config.profile["name"].split()
        profile_name = (state.get("linkedin_profile") or "").lower()
        if not (candidate[0].lower() in profile_name and candidate[-1].lower() in profile_name):
            # Signed out or signed in as someone else: never sign in; continue in cloud mode.
            ctx.mode = Mode.CLOUD
            ctx.linkedin_status = "not signed in as " + " ".join([candidate[0], candidate[-1]])
            return
        ctx.mode = Mode.CHROME
        ctx.linkedin_status = "searched as " + " ".join([candidate[0], candidate[-1]])
        for a in state.get("applied", []):
            ctx.do_not_repeat.append(DoNotRepeatEntry(
                company=a.get("company", ""), title=a.get("title", ""), link=a.get("link", ""),
                date=a.get("date", ""), status="Applied", source=f"applied-list:{a.get('site', '')}"))
        for p in state.get("postings", []):
            ctx.postings.append(JobPosting(**p))
        rep = ctx.site("LinkedIn")
        rep.searched, rep.found = True, len(state.get("postings", []))


class ChromeResultsAgent(Agent):
    """Merges chrome-applier outcomes into prepared jobs (report stage)."""

    name = "chrome_results"

    def __init__(self, results_path: str | None = None) -> None:
        super().__init__()
        self.results_path = results_path

    def run(self, ctx: RunContext) -> None:
        results = _load(self.results_path) or {}
        kept = []
        for job in ctx.prepared:
            r = results.get(job.posting.link)
            outcome = (r or {}).get("outcome")
            if outcome == "already_applied":
                ctx.skipped.append(SkippedJob(company=job.posting.company, title=job.posting.title,
                                              source=job.posting.source, link=job.posting.link,
                                              reason="Skipped - already handled (site shows Applied)",
                                              already_handled=True))
                continue
            if outcome == "review_reached":
                job.status = "Ready to submit (stopped at Review)"
            elif outcome in ("needs_account", "needs_answer"):
                job.status = "Needs manual sign-in" if outcome == "needs_account" else "Needs answer"
                job.risk = "; ".join(filter(None, [job.risk, r.get("detail", "")]))
            elif ctx.mode == Mode.CHROME and r is None:
                job.status = "Ready - Akshada applies"
                job.risk = "; ".join(filter(None, [job.risk, "application not opened in Chrome"]))
            kept.append(job)
        ctx.prepared = kept
