# `_audits/` — frozen run evidence

Each subdirectory is a frozen bundle of raw run artifacts (per-run JSON,
sample logs) backing one written report. **The readable entry point is the
`REPORT.md` inside each bundle** — the JSON is the evidence it folds, kept
verbatim so the report's numbers can be re-derived instead of trusted.

That is the repo's own rule applied to itself: a report is a claim, the run
artifacts are the witness, and the witness ships with the claim.
