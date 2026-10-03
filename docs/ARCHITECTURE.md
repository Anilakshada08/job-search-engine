# Architecture

The engine is a **code-orchestrated multi-agent pipeline**. A Python `Orchestrator` runs specialist
agents in a fixed order over one shared `RunContext` (a blackboard). LLM-backed agents call Claude
through the Anthropic SDK. Deterministic agents handle everything that must never be "argued with":
de-duplication, exclusions, truthfulness checks, dashboard JSON safety and git.

```
                        ┌──────────────────────────── RunContext (blackboard) ───────────────────────────┐
                        │ mode · do-not-repeat · postings · candidates · prepared · fyi · skipped · sites │
                        └──────────────────────────────────────────────────────────────────────────────────┘
 prepare ─┬─ ModeAgent ........... CHROME vs CLOUD (reads chrome-scout hand-off)            [code]
          ├─ HistoryAgent ........ Gmail run emails + dashboard + seed list -> do-not-repeat [LLM extract]
          ├─ FeedSearchAgent ..... Workable / RemoteOK / Jobicy / Himalayas / ATS JSON feeds [code]
          ├─ WebSearchAgent ...... 1 sub-agent per site, in parallel (web_search/web_fetch)  [LLM]
          ├─ DedupAgent(pre) ..... cross-site collapse + do-not-repeat match                 [code]
          ├─ ScreenerAgent ....... hard rules in code, then Angular-primary/location judge   [code+LLM]
          ├─ DedupAgent(post) .... staffing reposts of a handled end-client role            [code]
          └─ TailorAgent ......... score, tailor, truth-guard, render DOCX/PDF, verify PDF  [LLM+code]
 record  ─┬─ ChromeResultsAgent .. merge chrome-applier outcomes (Review reached / Applied)  [code]
          └─ DashboardAgent ...... append-only update of tracker-data JSON                  [code]
 publish ── PublisherAgent ....... index.html (+noindex) -> commit that file only -> main   [code]
 notify  ─┬─ ReporterAgent ....... the ONE run email, always (Gmail API, PDFs attached)     [code]
          └─ NotifierAgent ....... phone push only if >= 1 job is ready                     [code]
```

Each stage persists the context to `<output>/latest-run-state.json`, so stages can be run by
different runtimes (below).

## Two runtimes

| | Standalone Python (`jobhunt run`) | Claude Code routine (`routine/ROUTINE.md`) |
|---|---|---|
| Mode | always CLOUD | CHROME when Claude in Chrome is reachable |
| Browser work | none | `chrome-scout` and `chrome-applier` subagents |
| History | Gmail API | `history-auditor` subagent (Gmail connector) -> `--history-json` |
| Dashboard | repo `index.html` | artifact read -> `--dashboard-html` -> Artifact publish |
| Email | Gmail API with PDF attachments | same (engine `notify` stage) |

## Safety properties (enforced in code)

* **Never twice**: link/job-ID match, or same company (or end client) + near-identical title.
* **Never invent**: `enforce_truth` restores employer, client, title and dates from the base resume
  and drops any skill not in the profile. Match % is recomputed from a text search of the PDF.
* **Never submit**: the engine has no submit path; `chrome-applier` stops at Review.
* **Public repo**: personal data lives in gitignored `config/profile.yaml` /
  `config/do_not_repeat.yaml`; resumes go to `JOBHUNT_OUTPUT_DIR`, which must be outside the repo;
  the publisher commits only `index.html`.
* **Postings are data**: every LLM system prompt carries an injection guard; exclusions,
  clearance and citizenship are regex rules that a posting cannot talk its way past.
* **Dashboard**: append-only; existing statuses never change; JSON is escaped (`<` -> `<`).
