"""Publishes the dashboard HTML as the repo's index.html (step 5c). Commits ONLY that file."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROBOTS = '<meta name="robots" content="noindex,nofollow">'


def ensure_noindex(html: str) -> str:
    head = re.search(r"<head\b[^>]*>(.*?)</head>", html, re.S | re.I)
    if head and re.search(r"<meta\s+name=[\"']?robots", head.group(1), re.I):
        return html
    charset = re.search(r"<meta\s+charset[^>]*>", html, re.I)
    if charset:
        return html[: charset.end()] + ROBOTS + html[charset.end():]
    if head:
        pos = head.start(1)
        return html[:pos] + ROBOTS + html[pos:]
    return html


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {res.stderr.strip() or res.stdout.strip()}")
    return res.stdout.strip()


def publish_dashboard(repo: Path, source_html: Path, target: str = "index.html", remote: str = "origin",
                      branch: str = "main", message: str = "Update job dashboard") -> str:
    """Returns the email status line ("GitHub page: ...")."""
    try:
        current = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        if current != branch:
            return f"GitHub page: not updated - repository is on branch {current!r}, not {branch!r}"
        _git(repo, "fetch", remote, branch)
        _git(repo, "merge", "--ff-only", f"{remote}/{branch}")

        dest = repo / target
        html = ensure_noindex(source_html.read_text(encoding="utf-8"))
        if dest.exists() and dest.read_text(encoding="utf-8") == html:
            return "GitHub page: not updated - no changes"
        dest.write_text(html, encoding="utf-8", newline="")
        _git(repo, "add", "--", target)
        # Pathspec form commits only this file even if something else is staged.
        _git(repo, "commit", "-m", message, "--", target)
        _git(repo, "push", remote, f"HEAD:{branch}")
        return "GitHub page: updated"
    except Exception as e:
        return f"GitHub page: not updated - {e}"
