# 127 — DOS ↔ Bench/Job integration audit (2026-06-03)

> **Relocated to the `dos-private` repo**
> ([127 there](https://github.com/anthony-chaudhary/dos-private/blob/master/127_dos-bench-job-integration-audit-2026-06-03.md)).
> The audit's *subject* is the two private consumers of the kernel — the
> reference userland app and the benchmark host — at file/test/commit
> granularity, which is private-fleet prose, not kernel design. The doc moved;
> this stub stays so the many in-repo references to "the docs/127 audit
> cadence" keep resolving.

**What it was (the public-safe summary):** a 10-probe live integration audit
of the kernel against its first two consumers, run with real commands and an
adjudication pass. Its load-bearing public outcomes all landed in this repo:

- the **multi-way version-reporting drift** finding became the single-sourced
  version + drift-guard regime (`scripts/release_bump.py`,
  `tests/test_docs_version_drift.py`);
- the **"no release process" landmine** became the `/release` +
  `/stable-release` skills and their gates;
- the audit *genre* it established — re-run real commands across the seam on a
  cadence, grade each surface, flag what is unverified — recurs as
  `docs/186` and the `scripts/backflow_ledger.py --check` row.
