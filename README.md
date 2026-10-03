# job-search-engine

A multi-agent engine that finds Angular-primary developer jobs (Remote US or Chicago metro, posted in
the past 7 days), screens and de-duplicates them against everything already handled, writes a truthful
ATS resume for each 70%+ match, keeps the job dashboard up to date, and sends one summary email per run.

`index.html` at the repository root is the published dashboard (GitHub Pages, `noindex`).
Scheduled runs only ever commit that file.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the agent design and
[routine/ROUTINE.md](routine/ROUTINE.md) for the scheduled Claude Code routine.

## Layout

```
config/settings.yaml          committed, non-personal settings (sites, filters, thresholds, models)
config/*.example.yaml         templates for the gitignored personal files
src/jobhunt/orchestrator.py   stage runner over a shared RunContext
src/jobhunt/agents/           mode, history, feeds, web_search, dedup, screener, tailor,
                              dashboard_agent, publisher, reporter, notifier
src/jobhunt/resume/render.py  DOCX + PDF (Calibri) + small Helvetica attachment PDF, keyword check
src/jobhunt/dashboard.py      append-only tracker-data JSON editing
.claude/agents/               Claude Code subagents: chrome-scout, chrome-applier, history-auditor
tests/                        pytest suite (no network, no API calls)
```

## Setup

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
```

1. Copy `config/profile.example.yaml` to `config/profile.yaml` and `config/do_not_repeat.example.yaml`
   to `config/do_not_repeat.yaml`, then fill them in. Both files are gitignored. **Never commit them.**
2. Copy `.env.example` to `.env`. Set `JOBHUNT_OUTPUT_DIR` to a folder **outside** this repository; the
   engine refuses to write resumes inside it.
3. Anthropic credentials: `ANTHROPIC_API_KEY` or an `ant auth login` profile.
4. Gmail: create an OAuth "Desktop app" client with the Gmail API enabled, save the JSON outside the repo
   and point `GMAIL_CREDENTIALS_FILE` at it. The first run opens a consent page once and saves the token.

## Usage

```bash
jobhunt run --dry-run
```

```bash
jobhunt run
```

| Command | Purpose |
|---|---|
| `jobhunt run [--stage prepare\|record\|publish\|notify]` | whole pipeline, or a single stage |
| `jobhunt run --no-llm --dry-run` | feeds and rules only: no API calls, email, dashboard write or push |
| `jobhunt dashboard-append --html F --jobs J --run R` | safe append to a dashboard file |
| `jobhunt publish --html F` | copy to `index.html`, add `noindex`, commit only it, push to main |
| `jobhunt verify-pdf --pdf F --keywords "Angular,NgRx"` | text-search a resume PDF |

## Tests

```bash
.venv/Scripts/python -m pytest -q
```
