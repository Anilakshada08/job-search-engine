"""Notifier agent (step 6): phone push only when at least one new job is ready."""
from __future__ import annotations

import os

import httpx

from .base import Agent, RunContext


class NotifierAgent(Agent):
    name = "notifier"

    def run(self, ctx: RunContext) -> None:
        topic = os.environ.get("NTFY_TOPIC")
        if not ctx.prepared or ctx.dry_run or not topic:
            return
        names = ", ".join(f"{j.posting.company} ({j.match_percent}%)" for j in ctx.prepared[:5])
        try:
            httpx.post(f"https://ntfy.sh/{topic}", timeout=15,
                       content=f"{len(ctx.prepared)} Angular job(s) ready: {names}".encode(),
                       headers={"Title": "Job Apply Update"}).raise_for_status()
        except httpx.HTTPError as e:
            ctx.errors.append(f"notification failed: {e}")
