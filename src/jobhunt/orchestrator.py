"""Orchestrator: runs the specialist agents in order over a shared RunContext.

Stages (each persists the context to <output>/<date>/run-state.json so the next stage, possibly
started by a different runtime, can continue):

  prepare : mode -> history -> feeds + web search -> dedup -> screen -> dedup(end client) -> tailor
  record  : merge Chrome application outcomes -> append to dashboard tracker
  publish : copy dashboard to index.html, commit only that file, push to main
  notify  : send the ONE run email (always) -> phone push (only if jobs are ready)
  all     : every stage in order
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from .agents.base import Agent, RunContext
from .agents.dashboard_agent import DashboardAgent
from .agents.dedup import DedupAgent
from .agents.feeds import FeedSearchAgent
from .agents.history import HistoryAgent
from .agents.mode import ChromeResultsAgent, ModeAgent
from .agents.notifier import NotifierAgent
from .agents.publisher import PublisherAgent
from .agents.reporter import ReporterAgent
from .agents.screener import ScreenerAgent
from .agents.tailor import TailorAgent
from .agents.web_search import WebSearchAgent
from .config import Config
from .llm import LLM
from .models import Mode, PreparedJob, SiteReport, SkippedJob

log = logging.getLogger("jobhunt.orchestrator")
STAGES = ("prepare", "record", "publish", "notify")


class Orchestrator:
    def __init__(self, config: Config, *, use_llm: bool = True, dry_run: bool = False,
                 chrome_state: str | None = None, chrome_results: str | None = None,
                 dashboard_html: str | None = None, history_json: str | None = None):
        self.config = config
        self.ctx = RunContext(config=config, llm=LLM(config.settings) if use_llm else None, dry_run=dry_run)
        self.chrome_state = chrome_state
        self.chrome_results = chrome_results
        self.dashboard_html = dashboard_html
        self.history_json = history_json

    # -- pipeline ---------------------------------------------------------
    def agents_for(self, stage: str) -> list[Agent]:
        return {
            "prepare": [ModeAgent(self.chrome_state), HistoryAgent(self.history_json, self.dashboard_html), FeedSearchAgent(), WebSearchAgent(),
                        DedupAgent("pre"), ScreenerAgent(), DedupAgent("post"), TailorAgent()],
            "record": [ChromeResultsAgent(self.chrome_results), DashboardAgent(self.dashboard_html)],
            "publish": [PublisherAgent(self.dashboard_html)],
            "notify": [ReporterAgent(), NotifierAgent()],
        }[stage]

    def run(self, stage: str = "all") -> RunContext:
        stages = STAGES if stage == "all" else (stage,)
        if stages[0] != "prepare":
            self.load_state()
        for st in stages:
            for agent in self.agents_for(st):
                log.info("[%s] %s", st, agent.name)
                try:
                    agent.run(self.ctx)
                except Exception as e:  # one agent failing must not lose the run email
                    log.exception("agent %s failed", agent.name)
                    self.ctx.errors.append(f"{agent.name} agent failed: {e}")
            self.save_state()
        if self.ctx.llm:
            log.info("token usage: %s", self.ctx.llm.usage)
        return self.ctx

    # -- state hand-off between stages ------------------------------------
    @property
    def state_path(self) -> Path:
        return self.config.output_dir / self.ctx.started.astimezone().strftime("%Y-%m-%d") / "run-state.json"

    def save_state(self) -> None:
        c = self.ctx
        state = {
            "started": c.started.isoformat(), "mode": c.mode.value, "linkedin_status": c.linkedin_status,
            "prepared": [j.model_dump() for j in c.prepared], "fyi": [j.model_dump() for j in c.fyi],
            "skipped": [s.model_dump() for s in c.skipped], "sites": {k: v.model_dump() for k, v in c.sites.items()},
            "gaps": c.gaps, "errors": c.errors, "dashboard_line": c.dashboard_line, "github_line": c.github_line,
        }
        text = json.dumps(state, indent=1, default=str)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(text, encoding="utf-8")
        self.latest_path.write_text(text, encoding="utf-8")

    @property
    def latest_path(self) -> Path:
        return self.config.output_dir / "latest-run-state.json"

    def load_state(self) -> None:
        if not self.latest_path.exists():
            raise FileNotFoundError(f"{self.latest_path} not found; run the prepare stage first")
        s = json.loads(self.latest_path.read_text(encoding="utf-8"))
        c = self.ctx
        c.started = datetime.fromisoformat(s["started"])
        c.mode, c.linkedin_status = Mode(s["mode"]), s["linkedin_status"]
        c.prepared = [PreparedJob(**j) for j in s["prepared"]]
        c.fyi = [PreparedJob(**j) for j in s["fyi"]]
        c.skipped = [SkippedJob(**j) for j in s["skipped"]]
        c.sites = {k: SiteReport(**v) for k, v in s["sites"].items()}
        c.gaps, c.errors = s["gaps"], s["errors"]
        c.dashboard_line, c.github_line = s["dashboard_line"], s["github_line"]

