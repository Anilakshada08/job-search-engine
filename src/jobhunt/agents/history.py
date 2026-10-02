"""History agent: builds the do-not-repeat list before any job is touched.

Sources (step 3 of the routine):
  a. every "Job Apply Update" email in the last 90 days (LLM extraction over full thread text)
     plus every job in the dashboard tracker, whatever its status
  b. site "Applied" lists (only available in Chrome mode; supplied by the Chrome runtime)
  c. the always-on seed list in config/do_not_repeat.yaml
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from .. import dashboard
from ..integrations.gmail import Gmail
from .base import Agent, DoNotRepeatEntry, RunContext

HANDLED_STATUSES = ("submitted", "applied", "ready", "ready to submit", "needs akshada",
                    "needs action", "needs manual sign-in", "needs answer")


class EmailJob(BaseModel):
    company: str
    title: str
    link: str
    date: str
    status: str               # as written in the email (Submitted / Ready / Skipped ...)
    skip_reason: str          # "" unless the email skipped it
    skipped_only_for_age: bool


class EmailJobs(BaseModel):
    jobs: list[EmailJob]


EXTRACT_SYSTEM = (
    "You extract job entries from earlier job-search run summary emails. List every job mentioned, "
    "including skipped ones, with company, title, link (or empty), the email date, the status as "
    "written, and the skip reason if it was skipped. Set skipped_only_for_age=true only when the "
    "sole skip reason was that the posting was older than 24 hours / 1 day."
)


class HistoryAgent(Agent):
    name = "history"

    def __init__(self, history_json: str | None = None, dashboard_html: str | None = None) -> None:
        super().__init__()
        self.dashboard_html = dashboard_html
        # Optional pre-extracted history (e.g. from the Claude Code history-auditor subagent using
        # the Gmail connector). When given, the Gmail API is not called.
        self.history_json = history_json

    def run(self, ctx: RunContext) -> None:
        seed = ctx.config.do_not_repeat
        for j in seed.get("jobs", []):
            ctx.do_not_repeat.append(DoNotRepeatEntry(source="seed", **{k: str(v) for k, v in j.items()}))
        ctx.reevaluated_skips = list(seed.get("reevaluated_skips", []))

        self._from_dashboard(ctx)
        if self.history_json:
            for j in json.loads(Path(self.history_json).read_text(encoding="utf-8")):
                ctx.do_not_repeat.append(DoNotRepeatEntry(
                    company=j.get("company", ""), title=j.get("title", ""), link=j.get("link", ""),
                    date=j.get("date", ""), status=j.get("status", ""), source="history-json"))
        else:
            self._from_gmail(ctx)
        self.log.info("do-not-repeat list: %d entries", len(ctx.do_not_repeat))

    def _from_dashboard(self, ctx: RunContext) -> None:
        path = self.dashboard_html or ctx.config.repo_root / ctx.config.settings["dashboard"]["html_file"]
        try:
            data = dashboard.read_tracker(Path(path).read_text(encoding="utf-8"))
        except Exception as e:  # missing file or malformed block
            ctx.errors.append(f"dashboard read failed: {e}")
            return
        ctx.dashboard_data = data
        for j in data["jobs"]:
            ctx.do_not_repeat.append(DoNotRepeatEntry(
                company=j.get("company", ""), title=j.get("role", ""), link=j.get("link", ""),
                date=j.get("found", ""), status=j.get("status", ""), source="dashboard"))

    def _from_gmail(self, ctx: RunContext) -> None:
        days = ctx.config.settings["window"]["history_lookback_days"]
        try:
            gm = Gmail()
            threads = gm.search_threads(f'subject:"Job Apply Update" newer_than:{days}d')
            texts = [gm.thread_text(t) for t in threads]
        except Exception as e:
            ctx.errors.append(f"Gmail history unavailable: {e}")
            return
        if not texts or ctx.llm is None:
            return
        # Batch threads so one extraction call stays well inside the context window.
        batches: list[list[str]] = [[]]
        size = 0
        for t in texts:
            if batches[-1] and size + len(t) > 300_000:
                batches.append([])
                size = 0
            batches[-1].append(t)
            size += len(t)
        for b in batches:
            if b:
                self._extract(ctx, "\n\n=====\n\n".join(b))

    def _extract(self, ctx: RunContext, text: str) -> None:
        try:
            out = ctx.llm.structured(system=EXTRACT_SYSTEM, prompt=text, schema=EmailJobs, role="worker")
        except Exception as e:
            ctx.errors.append(f"history extraction failed: {e}")
            return
        for j in out.jobs:
            status = j.status.strip()
            if status.lower().startswith(HANDLED_STATUSES):
                ctx.do_not_repeat.append(DoNotRepeatEntry(
                    company=j.company, title=j.title, link=j.link, date=j.date, status=status, source="gmail"))
            elif j.skip_reason and not j.skipped_only_for_age:
                # Skipped for a non-age reason: stays skipped (3e).
                ctx.do_not_repeat.append(DoNotRepeatEntry(
                    company=j.company, title=j.title, link=j.link, date=j.date,
                    status=f"Skipped earlier: {j.skip_reason}", source="gmail"))
