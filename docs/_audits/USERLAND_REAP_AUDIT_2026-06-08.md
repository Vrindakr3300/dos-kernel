# Kernel userland-coupling audit — 2026-06-08

> **What this is.** A multi-agent sweep of every `src/dos/*.py` kernel module (drivers
> excluded) for host/userland-specific things that violate the CLAUDE.md layering
> contract and should be **reaped** (deleted, moved to a driver, or parameterized via
> config). Each candidate was adversarially verified against the real repo: does the
> named path/identifier actually exist here? is it runtime code or a provenance
> comment? is the module genuinely kernel-core? Method: `Workflow` run
> `wf_9827c080-70e` — 62 agents, 49 raw findings → 48 distinct → **42 confirmed, 6
> rejected**.

## Executive summary

The kernel is **mostly clean**, but one systemic leak is confirmed: the reference
**`job`** userland's *phased-plan workflow* has bled into ~15 kernel modules as
hardcoded paths, host lane names, commit-grammar regexes, host-named env keys, and —
worst — **live host-script imports**. Every confirmed host path glob
(`scripts/next_up*.py`, `docs/_plans/`, `docs/_fanout_runs/`, `output/next-up/`,
`scripts/fanout_state.py`, `contracts.py`, `next_up_context`, `model_registry`) is
**absent from this repo**, which is the proof they are foreign-host artifacts rather
than this workspace's own layout.

Three classes, by danger:

1. **Active kernel→host-tooling reaches (HIGH)** — `preflight.py` and `timeline.py`
   `sys.path.insert` a workspace/`__file__`-relative `scripts/` dir and `import` host
   modules by bare name, plus `preflight.py` shells a hardcoded `scripts/fanout_state.py`.
   The contract forbids this outright (rules 2/3/7/9). Inert *here* only because the
   target files don't exist — they execute host code against the real host workspace.
2. **Inert-but-contract-violating dead host policy (MEDIUM)** — host paths / lane names
   / commit-dialect regexes baked into modules advertised as generic. Archetype: the
   `_job_policy.py` "domain-free structural fallback" that still hardcodes the
   `orchestration` host globs, its own prose claiming they "were removed 2026-06-06".
   Includes a **vendor** leak: `cli.py` bakes the literal `claude` binary into a kernel
   constant, slipping the AST vendor-guard because it lives in a *string literal*.
3. **Documented back-compat seams (LOW)** — `config.job_config`, the `JOB_*` env
   aliases, the lazy re-exports. Real but **sanctioned** by litmus rule 2; these need
   owner sign-off, not mechanical reaping.

## The litmus rules applied (from CLAUDE.md)

1. Kernel imports no host (no `job`/`apply`/`tailor`/`discovery`/host-lane as a **code
   identifier** or **hardcoded host path glob**; prose/provenance allowed).
2. Kernel imports no host module. 3. Kernel never imports `scripts/`. 4. Never imports
`dos_mcp`. 5. Never imports `dos.drivers` (non-driver). 6. Names no vendor as a code
identifier (sole allowance: the `claude-code` default in `hook_dialect.py`). 7. No
phased-plan coupling (`execution-state.yaml`, soft-claims, plan-meta, `docs/_plans/`).
8. Shipped generic skills name no host. 9. Never assume the package lives in the repo
it serves (no `__file__` workspace anchor).

---

## STATUS (2026-06-08 — what landed)

Applied and committed (6 commits on `master`, each with its own green test run):

| Commit | Fixes | Files |
|---|---|---|
| `5017563` | the `orchestration` host-lane cluster (#4, #8, #9) | `_job_policy`, `arbiter`, `sibling_scan` |
| `f7fbc53` | the vendor `claude` binary leak (#7) | `cli`, `supervise` |
| `57d5602` | oracle phased-plan data-fication (#6, #12, #13, #15) | `oracle` |
| `cefd131` | host dispatcher prefixes + neutral sink-severity env (#10, #14) | `claim_ttl`, `event_severity` |

**Deferred to judgment calls (see below) — these turned out NOT to be cleanly
mechanical:** #1, #2, #3 (preflight/timeline), #5 (gh4_coverage), #11
(gate_classify replan-parse). The audit framed them as "excise the host reach," but
each is a **whole-module host-skill/workflow parser with no kernel caller** — the
contract-faithful fix is *relocation to `drivers/`*, which touches a host import
surface and so needs owner sign-off (it is the same bucket as the relocation
judgment calls). Half-parameterizing them in place leaves a hollow kernel shell the
host must fully configure — strictly worse than relocating. They are folded into the
judgment-call list with this finding.

The deeper oracle change (#6 full `cfg.paths`-derivation of the ledger basenames,
rather than the additive generic-names fix that landed) is also deferred: threading
`cfg` through the pure module-level demotion helpers is a truth-syscall-risk refactor,
not a mechanical edit. The landed fix already closes the *bug* (generic layout was
silently un-demoted); full derivation is the follow-up.

## CLEAR FIXES (unambiguous — safe to reap mechanically)

> ✅ = landed (see STATUS). ⏸ = deferred to judgment call (whole-module relocation).

| # | St | File | What | Sev | Fix |
|---|---|---|---|---|---|
| 1 | ⏸ | `preflight.py` | `_feature_flags_view()` (L116-128) `sys.path.insert(workspace/'scripts')` + `import next_up_context, model_registry` (absent host modules) | **HIGH** | → relocation (whole module is host-workflow; see judgment calls). |
| 2 | ⏸ | `preflight.py` | `list_active_filtered()` (L385-388) shells hardcoded `scripts/fanout_state.py list-active --json` | **HIGH** | → relocation (same module). |
| 3 | ⏸ | `timeline.py` | L45-54 `sys.path.insert(__file__ parent)` + `from contracts import …` (host `scripts/contracts.py`, absent) | **HIGH** | → relocation (whole module is the host dispatch-run renderer). |
| 4 | ✅ | `_job_policy.py` | `JOB_LANE_TAXONOMY.trees['orchestration']` hardcodes host phased-plan globs — the **confirmed seed**; code contradicts its own "structural ONLY" prose | MED | DONE: dropped the host globs (exclusive lanes are EXEMPT from `LANE_WITHOUT_TREE`); host globs → consumer `dos.toml`. |
| 5 | ⏸ | `gh4_coverage.py` | `STAMP_PATTERNS_GENERIC`/`FANOUT_TS_RE` named "GENERIC" but encode host dialect `^docs/dispatch:`/`docs/_fanout_runs`. **Zero importers** in `src/dos/` (dead leaf) | MED | → relocation (whole module is a host-dialect lift with no kernel caller). |
| 6 | ✅* | `oracle.py` | `_DISPATCH_LEDGER_BASENAMES` hardcoded the reference filenames only; generic layout (`dos.state.yaml`/`dos.findings.md`) was silently un-demoted | MED | DONE (partial): added the generic-layout basenames (fixes the bug); full `cfg.paths`-derivation deferred (truth-syscall threading risk). |
| 7 | ✅ | `cli.py` | `_LOOP_SPAWN_CMD = 'claude -p "…"'` bakes the **vendor** `claude` binary into a kernel constant; AST guard misses string literals | MED | DONE: `SupervisePolicy.worker_launch_template` (vendor-neutral default); constant deleted; test strengthened to forbid `claude`. |
| 8 | ✅ | `arbiter.py` | host lane `'orchestration'` hardcoded as a runtime admission literal (L329/466/468/510/520) | MED | DONE: drive off `cfg.lanes.exclusive` (`exclusive_lanes`); `global` stays the generic constant. |
| 9 | ✅ | `sibling_scan.py` | `exclusive_lanes` default `('global','orchestration')`; docstring falsely said "main/global" | MED | DONE: default `('global',)`; docstring fixed; host passes `cfg.lanes.exclusive`. |
| 10 | ✅ | `claim_ttl.py` | `infer_kind()` matches host dispatcher prefixes `fanout-`/`next-up-` | MED | DONE: `dispatcher_kinds` param, empty default; kernel names no host prefix. |
| 11 | ⏸ | `gate_classify.py` | `REPLAN_NOOP_SKIP_MARKER` + `_REPLAN_WORK_PATTERNS` regex-scrape host `/replan §7` gardening prose; no kernel caller (`loop_decide` reads the verdict, doesn't call the parser) | MED | → relocation (whole function parses one host skill's output format). |
| 12 | ✅ | `oracle.py` | `_RELEASE_BUMP_PREFIXES` hardcoded host `docs/06_implementation-status` | MED | DONE: dropped the host literal; kept generic `docs/releases/`. |
| 13 | ✅ | `oracle.py` | `_PLAN_DOC_RE` hardcoded host `^docs/…-plan.md$`; riverflow example (`experiments/*.md`) proves it's not universal | MED | DONE: match any `*-plan.md` path (basename-decided anyway); behavior-identical for `docs/`-rooted. |
| 14 | ✅ | `event_severity.py` | `_SINK_ENV` read `JOB_DISPATCH_*_MIN_SEVERITY` as the **sole** namespace | MED | DONE: neutral `DISPATCH_*` primary + `JOB_*` documented fallback. |
| 15 | ✅ | `oracle.py` | soak markers hardcode `docs/_soaks/index.yaml` in operator strings | LOW | DONE: interpolate `cfg.paths.soaks_index` via `_soaks_path()`. |

## JUDGMENT CALLS (real findings needing owner sign-off — back-compat or architectural)

- **`config.py` `PathLayout.for_root`** (L280-299) — builds the reference host layout
  (`docs/_plans/…`, `docs/_fanout_runs`, `output/next-up`, `findings-followup-queue.md`)
  as runtime path values in a layer-2a module, reached via `job_config()`. Honest
  docstring; generic `for_dos_dir` exists beside it. **Tradeoff:** relocate
  `for_root`+`job_config` to `drivers/job.py` (matches contract) vs. it's a documented
  re-export a reference consumer pins. MED.
- **`config.py` + `stamp.py` stamp default** — `SubstrateConfig.stamp` defaults to
  `JOB_STAMP_CONVENTION` (host `subject_dirs`/prefixes/`fanout_state.py`).
  `default_config()` overrides to GENERIC; `job_config()` relies on the implicit JOB
  default. **Tradeoff:** flip the dataclass default to GENERIC + set JOB explicitly in
  `job_config` (symmetric, contract-correct) vs. `JOB_STAMP_CONVENTION` is a documented
  byte-for-byte back-compat seam pinned by `test_stamp_convention.py`. MED.
- **`preflight.py` whole-module** — beyond the 3 HIGH reaches, the module is bound to
  the host `/next-up`→`/fanout` packet schema (`EXPECTED_PACKET_SCHEMA='next-up-packet-v1'`,
  `.prompts.json`, `.verdict-<tag>.json` envelopes, soft-claim registry). **Tradeoff:**
  relocate the bundler to `drivers/` (contract-faithful) vs. accept the banner is
  aspirational. MED.
- **`timeline.py` whole-module** — beyond the `contracts` import, hardcodes
  `docs/contracts/dispatch` + reconstructs the host two-child chained-run model
  (`next-up.json`/`fanout.json` envelopes, README breadcrumbs, `step_trace.StepTrace`).
  Dual-listed in CLAUDE.md (layer-1 + layer-3); has its own `main()`, NOT on the `dos`
  CLI. **Tradeoff:** relocate to `drivers/` (low-risk — not CLI-wired) vs. generify to
  read only kernel state. MED.
- **`gate_classify.py` `PickDisposition` model** — encodes host phased-plan concepts
  (`plan_doc_stamped`, `DROP_SOFT_CLAIMED`, `is_stale_stamp`, `oc3-dispositions-v1` /
  `next-up-race-v1` schema tags). **Tradeoff:** schema-tag constants are
  sanctioned-pattern (mild); the soft-claim/plan-stamp **verdict vocabulary** is the
  real question — relocate `gate_classify`(+`loop_decide`) to a driver, or keep a
  generic packet-gate and let the host supply the evidence model. Larger refactor. MED.
- **`loop_decide.py`** (L1131-1137) — branches on `self_heals_via != '/replan'` →
  `/unstick`. These are DOS's *own* shipped skills (DOS-native, not foreign), and the
  STOP verdict is decided by `outcome.verdict` not this compare. Stale foreign
  docstrings cite `scripts/headless_telemetry.py`, `FQ-452`/`FQ-510`. **Tradeoff:**
  low-value to reap; at most scrub the stale docstrings. LOW.
- **`oracle.py`/`picker_oracle.py` `JOB_FANOUT_STATE_PATH`** (L101/L98) — host-named env
  var. Documented (docs/75 §6.4), test-pinned, generic-`DISPATCH_`-primary fallback.
  **Default: leave it** (the explicitly-tolerated seam). LOW.
- **`lane_journal.py`/`lane_lease.py` `JOB_LANE_JOURNAL_PATH`** (L98/L197/L83) —
  same class; documented back-compat alias, generic-primary. **Default: leave it.** LOW.
- **`config.py` `JOB_LANE_TAXONOMY` re-export** + **`cli.py` `--job`/`driver='job'`** —
  thin name-forwarding shims; rule 2 explicitly sanctions them; the reapable *content*
  is the `_job_policy` seed, not these. LOW.
- **`provider_limit.py` `from_apply_outcome_token()`** (L212-223) — hardcodes one host's
  `apply-next-loop` outcome-token vocabulary; **unimported** in `src/dos/`. **Tradeoff:**
  move to a driver / host config vs. leave the one-way translator. Clean to reap (dead)
  but harmless until invoked. LOW.

## Rejected (6) — correctly NOT findings

The verifiers rejected 6 candidates as provenance comments, generic words (`apply` the
PEP verb, `discovery` = entry-point discovery), driver-resident code, or false
positives. Full detail in the run journal (`wf_9827c080-70e`).

## Cross-cutting observations

- **The `orchestration` lane is the most-widespread single leak** — it appears as a
  runtime literal in `arbiter.py`, `sibling_scan.py`, and `_job_policy.py`. It is
  arguably *kernel vocabulary* (like `global`), but it is hardcoded rather than driven
  off `cfg.lanes.exclusive`, and two docstrings falsely call the surrounding default
  "generic main/global".
- **The AST vendor-guard has a hole:** `test_vendor_agnostic_kernel.py` inspects only
  `ast.Name`/`ast.Attribute`, so a vendor name inside a **string literal** (the
  `cli.py` `claude` constant) passes. Worth extending the guard to string constants.
- **`oracle.py` is the densest single module** — 5 distinct host couplings
  (`_DISPATCH_LEDGER_BASENAMES`, `_RELEASE_BUMP_PREFIXES`, `_PLAN_DOC_RE`, the soak
  markers, the `JOB_` env var), all on or near the `verify()` truth-syscall path.
- **The kernel has no single litmus test that walks every module.** The no-host /
  no-vendor checks are applied *per-module* (`test_attest.py`, `test_coverage.py`,
  etc.), so a module with no such test (like `_job_policy.py`, which by nature can't
  have one) escapes. A repo-wide AST sweep test would close this.
