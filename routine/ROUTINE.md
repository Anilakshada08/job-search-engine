# Scheduled routine (Claude Code runtime)

Run from the repository root by the scheduled Claude Code task. The main session is the
orchestrator; browser and mailbox work goes to subagents in `.claude/agents/`; the deterministic
work goes to the `jobhunt` engine. The `angular-job-apply` skill remains the source of the
candidate profile, base resume, saved answers and exclusions (mirrored in the gitignored
`config/profile.yaml`). Where the skill and the routine prompt differ, the prompt wins.

Use a run folder outside the repository, e.g. `$JOBHUNT_OUTPUT_DIR/<date>/`.

1. **Mode** - delegate to `chrome-scout` (output: `chrome_state.json`). It writes
   `{"reachable": false}` when Chrome is unreachable (CLOUD MODE).
2. **History** - delegate to `history-auditor` (output: `history.json`). Also read the dashboard
   artifact (Artifact tool, action `read`); the engine adds every tracker job to the do-not-repeat list.
3. **Prepare** -
   `jobhunt run --stage prepare --chrome-state chrome_state.json --history-json history.json --dashboard-html <artifact file>`
   Searches the feeds and sites, de-duplicates, screens, tailors and renders resumes, and checks each keyword in the PDF.
4. **Apply (CHROME MODE only)** - delegate the engine's `prepared` list to `chrome-applier`
   (output: `chrome_results.json`). It stops at Review and never submits.
5. **Record** - `jobhunt run --stage record --chrome-results chrome_results.json --dashboard-html <artifact file>`
6. **Dashboard** - publish the edited file with the Artifact tool (`publish`, `url` = dashboard,
   no capabilities/icon/contract/force). On conflict: read again, re-run step 5 on the new file,
   publish once more. Note the result for the email's `Dashboard:` line.
7. **GitHub page** - read the artifact again, then `jobhunt publish --html <fresh artifact file>`
   (adds noindex if missing, commits only `index.html` with "Update job dashboard", pushes to main).
8. **Email + notification** -
   `jobhunt run --stage notify --dashboard-line "Dashboard: ..." --github-line "GitHub page: ..."`
   It always sends one email and pushes a phone notification only when a job is ready.
   In the Claude Code runtime, use the PushNotification tool instead of ntfy.

Never: type passwords, create accounts, solve CAPTCHAs, enter SSN/ID/DOB, inflate experience,
click Submit, or commit anything except `index.html`.
