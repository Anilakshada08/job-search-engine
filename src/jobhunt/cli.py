"""Command line entry point: ``jobhunt <command>`` or ``python -m jobhunt <command>``."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


def _run(args) -> int:
    from .config import load_config
    from .orchestrator import Orchestrator

    orch = Orchestrator(load_config(), use_llm=not args.no_llm, dry_run=args.dry_run,
                        chrome_state=args.chrome_state, chrome_results=args.chrome_results,
                        dashboard_html=args.dashboard_html, history_json=args.history_json)
    if args.stage not in ("all", "prepare"):
        orch.load_state()
    if args.dashboard_line:
        orch.ctx.dashboard_line = args.dashboard_line
    if args.github_line:
        orch.ctx.github_line = args.github_line
    ctx = orch.run(args.stage) if args.stage in ("all", "prepare") else _run_loaded(orch, args.stage)
    print(json.dumps({
        "mode": ctx.mode.value, "ready": len(ctx.prepared), "fyi": len(ctx.fyi), "skipped": len(ctx.skipped),
        "dashboard": ctx.dashboard_line, "github": ctx.github_line, "errors": ctx.errors,
        "prepared": [{"company": j.posting.company, "title": j.posting.title, "link": j.posting.link,
                      "match": j.match_percent, "resume_pdf": j.resume_pdf, "status": j.status}
                     for j in ctx.prepared],
    }, indent=1))
    return 0


def _run_loaded(orch, stage: str):
    """Run one later stage on already-loaded state (keeps CLI line overrides)."""
    for agent in orch.agents_for(stage):
        try:
            agent.run(orch.ctx)
        except Exception as e:
            orch.ctx.errors.append(f"{agent.name} agent failed: {e}")
    orch.save_state()
    return orch.ctx


def _dashboard_append(args) -> int:
    from . import dashboard

    jobs = json.loads(Path(args.jobs).read_text(encoding="utf-8")) if args.jobs else []
    run = json.loads(Path(args.run).read_text(encoding="utf-8"))
    added = dashboard.update_file(args.html, jobs, run)
    print(json.dumps({"added": added}))
    return 0


def _publish(args) -> int:
    from .config import REPO_ROOT, load_config
    from .integrations.github import publish_dashboard

    gh = load_config().settings["github"]
    print(publish_dashboard(REPO_ROOT, Path(args.html), gh["publish_file"], gh["remote"], gh["branch"],
                            gh["commit_message"]))
    return 0


def _verify_pdf(args) -> int:
    from .resume.render import pdf_pages, verify_keywords

    missing = verify_keywords(Path(args.pdf), [k.strip() for k in args.keywords.split(",") if k.strip()])
    print(json.dumps({"pages": pdf_pages(Path(args.pdf)), "missing": missing}))
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jobhunt", description="Multi-agent Angular job search engine")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the pipeline (or one stage of it)")
    r.add_argument("--stage", default="all", choices=["all", "prepare", "record", "publish", "notify"])
    r.add_argument("--chrome-state", help="JSON from the chrome-scout subagent (enables CHROME MODE)")
    r.add_argument("--history-json", help="pre-extracted do-not-repeat entries (skips the Gmail API)")
    r.add_argument("--chrome-results", help="JSON from the chrome-applier subagent")
    r.add_argument("--dashboard-html", help="dashboard HTML to append to / publish (default: repo index.html)")
    r.add_argument("--dashboard-line", help="override the email's Dashboard: line")
    r.add_argument("--github-line", help="override the email's GitHub page: line")
    r.add_argument("--dry-run", action="store_true", help="no email, no dashboard write, no push")
    r.add_argument("--no-llm", action="store_true", help="feeds + rules only (no Anthropic calls)")
    r.set_defaults(fn=_run)

    d = sub.add_parser("dashboard-append", help="append jobs + a run record to a dashboard HTML file")
    d.add_argument("--html", required=True)
    d.add_argument("--jobs", help="JSON list of job objects")
    d.add_argument("--run", required=True, help="JSON run record")
    d.set_defaults(fn=_dashboard_append)

    p = sub.add_parser("publish", help="copy dashboard HTML to index.html, commit it alone, push to main")
    p.add_argument("--html", required=True)
    p.set_defaults(fn=_publish)

    v = sub.add_parser("verify-pdf", help="text-search a resume PDF for keywords")
    v.add_argument("--pdf", required=True)
    v.add_argument("--keywords", required=True, help="comma separated")
    v.set_defaults(fn=_verify_pdf)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
