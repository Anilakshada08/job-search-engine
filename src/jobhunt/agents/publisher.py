"""Publisher agent (step 5c): copies the dashboard to index.html and pushes it to main."""
from __future__ import annotations

from pathlib import Path

from ..integrations.github import publish_dashboard
from .base import Agent, RunContext


class PublisherAgent(Agent):
    name = "publisher"

    def __init__(self, html_path: str | None = None) -> None:
        super().__init__()
        self.html_path = html_path

    def run(self, ctx: RunContext) -> None:
        gh = ctx.config.settings["github"]
        src = Path(self.html_path) if self.html_path else ctx.config.repo_root / gh["publish_file"]
        if ctx.dry_run:
            ctx.github_line = "GitHub page: not updated - dry run"
            return
        ctx.github_line = publish_dashboard(ctx.config.repo_root, src, gh["publish_file"], gh["remote"],
                                            gh["branch"], gh["commit_message"])
