"""Reporter agent: composes and sends the ONE run email (step 5), always - even with 0 jobs."""
from __future__ import annotations

from collections import Counter
from html import escape
from pathlib import Path

from ..integrations.gmail import Gmail
from ..models import PreparedJob
from .base import Agent, RunContext


def top_gaps(ctx: RunContext, n: int = 3) -> list[str]:
    return [g for g, _ in Counter(g for g in ctx.gaps if g).most_common(n)]


def subject(ctx: RunContext) -> str:
    m = len(ctx.prepared)
    s = f"{ctx.config.settings['email']['subject_prefix']} - {ctx.date_str} - 0 submitted, {m} ready"
    return s + (" (no new Angular jobs)" if m == 0 else "")


def _job_rows(j: PreparedJob, answers: dict) -> list[tuple[str, str]]:
    p = j.posting
    acct = {True: "account needed", False: "no account needed", None: "account: unknown"}[j.needs_account]
    return [
        ("Company", p.company), ("Role", p.title),
        ("Location / type", " / ".join(filter(None, [p.location, p.job_type]))),
        ("Posted", (p.posted or "unknown") + (" (date unclear)" if p.date_unclear else "")),
        ("Apply via", f"{j.apply_via} ({acct})"), ("Status", j.status), ("Match", f"{j.match_percent}%"),
        ("Screening answers", f"Angular/JavaScript/TypeScript {answers.get('years_angular', 7)} years; "
                              f"Green Card, sponsorship: {answers.get('requires_sponsorship', 'No')}"),
        ("Risk", j.risk or "-"), ("Recruiter", p.recruiter or "-"), ("Link", p.link),
        ("Resume", Path(j.resume_pdf).name if j.resume_pdf else "-"),
        ("Also on", ", ".join(p.other_sites) or "-"),
    ] + ([("Keywords not found in PDF", ", ".join(j.missing_on_pdf))] if j.missing_on_pdf else [])


def build_bodies(ctx: RunContext, attach_note: str = "") -> tuple[str, str]:
    answers = ctx.config.profile.get("saved_answers", {})
    T, H = [], []

    def line(text: str, tag: str = "p"):
        T.append(text)
        H.append(f"<{tag}>{escape(text)}</{tag}>")

    line(f"Mode: {ctx.mode.value}", "p")
    line(f"Ready jobs ({len(ctx.prepared)})", "h2")
    for j in ctx.prepared:
        rows = _job_rows(j, answers)
        T.append("\n".join(f"  {k}: {v}" for k, v in rows) + "\n")
        H.append("<ul>" + "".join(
            f"<li><b>{escape(k)}:</b> " + (f'<a href="{escape(v)}">{escape(v)}</a>' if k == "Link" else escape(v))
            + "</li>" for k, v in rows) + "</ul>")
    if not ctx.prepared:
        line("No new Angular job met the 70% bar this run.")

    line("50-69% matches (FYI)", "h2")
    for j in ctx.fyi or []:
        line(f"{j.posting.company} - {j.posting.title} ({j.match_percent}%, {j.posting.source}) {j.posting.link}", "li")
    if not ctx.fyi:
        line("None.")

    line(f"LinkedIn: {ctx.linkedin_status}")
    line(ctx.dashboard_line)
    line(ctx.github_line)

    handled = sum(1 for s in ctx.skipped if s.already_handled)
    line(f"Skipped ({len(ctx.skipped)}; already handled: {handled})", "h2")
    for s in ctx.skipped:
        line(f"{s.company} - {s.title} [{s.source}]: {s.reason}", "li")

    line("Sites", "h2")
    for r in ctx.sites.values():
        status = f"unavailable - {r.unavailable}" if r.unavailable else ("searched" if r.searched else "not searched")
        line(f"{r.site}: {status}; found {r.found}, kept {r.kept}", "li")

    line("Top gap keywords: " + (", ".join(top_gaps(ctx)) or "none"))
    if ctx.errors:
        line("Run notes", "h2")
        for e in ctx.errors:
            line(e, "li")
    if attach_note:
        line(attach_note)
    return "\n".join(T), "<html><body>" + "\n".join(H) + "</body></html>"


class ReporterAgent(Agent):
    name = "reporter"

    def run(self, ctx: RunContext) -> None:
        to = ctx.config.settings["email"]["to"]
        attachments = [Path(j.attachment_pdf) for j in ctx.prepared if j.attachment_pdf and Path(j.attachment_pdf).exists()]
        text, html = build_bodies(ctx)
        out = ctx.config.output_dir / ctx.started.astimezone().strftime("%Y-%m-%d")
        out.mkdir(parents=True, exist_ok=True)
        (out / "email.html").write_text(html, encoding="utf-8")
        if ctx.dry_run:
            self.log.info("dry run: email written to %s", out / "email.html")
            return
        try:
            gm = Gmail()
        except Exception as e:
            ctx.errors.append(f"email not sent - Gmail unavailable: {e}")
            return
        try:
            gm.send(to, subject(ctx), html, text, attachments)
        except Exception as e:
            # Attachments too large or rejected: send with file names listed instead.
            names = ", ".join(p.name for p in attachments)
            text, html = build_bodies(ctx, f"Attachments could not be sent ({e}); resume files: {names}")
            gm.send(to, subject(ctx), html, text, [])
