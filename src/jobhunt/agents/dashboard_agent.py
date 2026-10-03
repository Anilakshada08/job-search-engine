"""Dashboard agent (step 5b): appends this run's new jobs and one run record to the tracker JSON.

Target file: the dashboard artifact's local HTML copy (Claude Code runtime passes it with
--dashboard-html after reading the artifact), or the repo's index.html when run standalone.
Publishing the artifact itself is done by the Claude Code runtime (Artifact tool).
"""
from __future__ import annotations

from pathlib import Path

from .. import dashboard
from ..models import Mode, PreparedJob
from ..textutil import slug
from .base import Agent, RunContext
from .reporter import top_gaps

STATUS_MAP = {
    "Ready - Akshada applies": "Ready",
    "Ready to submit (stopped at Review)": "Ready",
    "Needs manual sign-in": "Needs Akshada",
    "Needs answer": "Needs Akshada",
    "Submitted": "Applied",
}


def job_record(j: PreparedJob, found: str) -> dict:
    p = j.posting
    acct = {True: "account needed", False: "no account needed", None: "account unknown"}[j.needs_account]
    return {
        "id": slug(p.company, p.title), "company": p.company, "role": p.title, "location": p.location,
        "type": p.job_type, "status": STATUS_MAP.get(j.status, "Ready"), "match": j.match_percent,
        "found": found, "source": p.source, "applyVia": f"{j.apply_via} ({acct})", "link": p.link,
        "resume": Path(j.resume_pdf).name if j.resume_pdf else "", "risk": j.risk,
        "notes": "; ".join(filter(None, [j.status, "Also on: " + ", ".join(p.other_sites) if p.other_sites else "",
                                         "date unclear" if p.date_unclear else ""])),
    }


class DashboardAgent(Agent):
    name = "dashboard"

    def __init__(self, html_path: str | None = None) -> None:
        super().__init__()
        self.html_path = html_path

    def run(self, ctx: RunContext) -> None:
        path = Path(self.html_path) if self.html_path else \
            ctx.config.repo_root / ctx.config.settings["dashboard"]["html_file"]
        found = ctx.started.astimezone().strftime("%Y-%m-%d")
        new_jobs = [job_record(j, found) for j in ctx.prepared]
        reviewed = sum(r.found for r in ctx.sites.values())
        run = {
            "at": dashboard.utc_now_iso(), "mode": "Chrome" if ctx.mode == Mode.CHROME else "Cloud",
            "reviewed": reviewed, "ready": len(new_jobs),
            "summary": (f"{len(new_jobs)} new Angular job(s) ready" if new_jobs else "No new Angular jobs")
                       + f"; {sum(1 for s in ctx.skipped if s.already_handled)} already handled",
            "gaps": top_gaps(ctx),
        }
        if ctx.dry_run:
            ctx.dashboard_line = "Dashboard: not updated - dry run"
            return
        try:
            added = dashboard.update_file(path, new_jobs, run)
            ctx.dashboard_line = f"Dashboard: updated ({len(added)} job(s) added)"
        except Exception as e:
            ctx.dashboard_line = f"Dashboard: not updated - {e}"
