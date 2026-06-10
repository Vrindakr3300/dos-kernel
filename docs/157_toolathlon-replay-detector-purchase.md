# Toolathlon as a DOS test target — the $0 replay, and DETECT-not-FIX on a third-party-scored benchmark

> **A new external benchmark — Toolathlon ("The Tool Decathlon", ICLR 2026,
> `hkust-nlp/Toolathlon`) — is the cleanest test target DOS has had, for one reason
> EnterpriseOps-Gym (EOG) structurally cannot offer: its ground-truth oracle is
> authored by a THIRD PARTY, not by us. 32 MCP apps, 604 tools, 108 long-horizon
> (~20-turn) cross-app tasks, each scored by an independent `evaluation/main.py` that
> reads live app state and exits 0/1 — the agent's `claim_done` self-report cannot
> produce a pass. So DOS's `verify()` rung already exists inside Toolathlon and DOS
> does not own it; the only open question DOS can answer is whether its IN-FLIGHT,
> byte-clean detectors add purchase over the strong models the leaderboard runs. This
> doc answers it the way the cost dictates: NOT a live A/B (the FIX half EOG already
> returned null on for capable models), but a ~$0 REPLAY over the published
> `Toolathlon-Trajectories` dataset (22 models × 3 runs × ~108 tasks, CC-BY-4.0),
> each record carrying the full conversation AND the third-party pass/fail label. We
> fold `dos.dangling_intent` and `dos.tool_stream` — the two MINT-INDEPENDENT
> detectors that fire on any looping/premature-stopping model, the half EOG
> under-exercised — over every frozen trajectory and report detector PURCHASE
> (fire-rate + oracle-confirmed precision), never task LIFT. The finding reproduces
> the EOG track record on a public benchmark: the detectors fire with HIGH precision
> and LOW recall, with purchase that vanishes on the strongest model — DETECT
> generalizes; the narrating/looping-subset ceiling holds; there is no lift number
> because a frozen trajectory had no intervention. That null is the honest,
> publishable result.**

**Status:** Phases 1–2 SHIPPED — `benchmark/toolathlon/`, **23 tests green**, full-corpus run
(7,116 records / 22 models). Phase 2 delivered: the 4 figures (`viz.py`), the `result_digest`
normalizer (`trajectory.normalize_result_bytes`, default-on), the durable rows + `schema.md`, and
the §4 writeup (with the adversarially-verified "normalizer lifted recall not false-alarms"
finding). Phase 3 (live single-task seam smoke) specced; **Phase 4 (the live none-vs-WARN A/B that
produces a LIFT number — the move that makes this publishable) has a ready-to-run prompt in
`benchmark/toolathlon/HANDOFF.md`.** See that file.

**Lineage / cross-index.** This doc is the engineering companion to the strategy-side
[`dispatch-os-the-verification-substrate-for-agentic-rl.md`](../../dos-private/dispatch-os-the-verification-substrate-for-agentic-rl.md)
(Toolathlon is the concrete external benchmark its abstract syscall→RL map targets). It
inherits the detector doctrine from `docs/143` (arg_provenance, the −9pp WARN-only lesson),
`docs/144` (the intervention ladder), `docs/145` (`tool_stream`, the mint-independent loop
axis), `docs/150`/`docs/152` (`dangling_intent`, the premature-completion crack), and
`docs/153` (the weak-model lift question). It is the FIRST DOS study scored by an oracle DOS
did not author.

---

## 1. What Toolathlon is (VERIFIED from source, 2026-06-05)

Read directly off `github.com/hkust-nlp/Toolathlon` via `gh api` and the paper (arXiv 2510.25726v2):

- **Scale:** 32 MCP servers = **604 tools** (+ 7 local toolkits / 16 tools incl. `claim_done`,
  `python`, `web_search`, context/history mgmt). **108 scored tasks** under `tasks/finalpool/`,
  ~20 turns/task, predominantly **cross-app** (design principle: "we intentionally source tasks
  that require interaction with multiple MCP servers"). **18 of 32 servers MUTATE real
  third-party state** (Canvas grade, sent email via Poste, Notion row, k8s deploy, WooCommerce
  order); 14 read-only.
- **Execution-based final-state verification (the load-bearing fact):** each task ships
  `tasks/finalpool/<task>/evaluation/main.py`, an INDEPENDENT process invoked with
  `--res_log_file --agent_workspace --groundtruth_workspace --launch_time`; it reads LIVE app
  state (live MySQL via `pymysql`, k8s via `ps aux`/kubeconfig, GCS/Cloud Logging/Sheets/IMAP)
  and exits 0/1 → `task_status.evaluation` ∈ {true, false}. Verified one directly:
  `find-alita-paper/evaluation/main.py` hash-compares the ACTUAL PDF the agent downloaded against
  a freshly-fetched arxiv ground truth. **The agent's `claim_done` is a status GATE only — it
  cannot produce `evaluation=true`.** Byte-author of the verified state is the app/infra, not the
  judged agent — DOS's core invariant (`byte-author ≠ judged agent`) holds by construction.
- **Single agent per task on isolated state** (`main.py` → `TaskRunner.run_single_task` → one
  `TaskAgent`; `run_parallel.py` parallelizes ACROSS isolated tasks — fresh container + per-task
  Kind cluster — never multiple agents inside one task's state).
- **Scaffold:** two SDK-managed codepaths chosen by a bash `case` in `run_single_decoupled.sh` —
  `toolathlon_default` (OpenAI Agents SDK, already monkey-patched at
  `utils/openai_agents_monkey_patch/custom_run_impl.py`) and `claude_agent_sdk`. **There is NO
  user-owned for-loop to subclass** the way EOG's `orchestrators/react.py` has — the EOG-subclass
  reuse story does NOT transplant (corrected from the first-pass plan).
- **Top models <55%:** the paper's own table tops at **Claude-4.5-Sonnet 38.6% Pass@1** (GPT-5
  30.6, Gemini-2.5-Flash **3.7**). The "<55% / Gemini-3.5-Flash 56.5%" figure is the live mid-2026
  leaderboard, INFERRED-not-from-paper. Pass^3 collapses (Sonnet 20.4) — "they lack consistency".
- **Documented failure modes (paper §5/C.2, rank order):** (1) **premature termination /
  "laziness"** — the headline (`music-analysis`: 66 turns, does year 1940, says "the same steps
  can be applied… [Claim Done]"); (2) incompleteness in complex states; (3) tool-calling errors
  (often self-correct — the env feeds errors back); (4) fuzzy-intent failures; (5) long-context
  degradation.

The published trajectories: **`huggingface.co/datasets/hkust-nlp/Toolathlon-Trajectories`** — **66
JSONL files (22 models × 3 runs)**, 7,116 records (the README's "17×3" is stale; the live dataset is
22×3), CC-BY-4.0. Each record (VERIFIED schema):
`{modelname_run, task_name, task_status (JSON str: preprocess/running/evaluation), config,
tool_calls (JSON str: the available-tool schema), messages (OpenAI chat: assistant tool_calls
answered by tool messages by tool_call_id), key_stats, agent_cost}`.

## 2. Why a REPLAY, not a live A/B (the cost-corrected decision)

The first-pass plan reached for a live none-vs-WARN A/B. Three adversarial passes moved it:

1. **The FIX half is the half EOG already returned NULL on for capable models.** EOG's
   `dangling_intent` FIX was inert (0/9 fired stops converted to a pass): a capable model stops
   because it COULD NOT form the next step, not from laziness, so re-surfacing its own sentence
   hands back the wall it hit. Toolathlon's leaderboard models are capable. A live A/B would most
   likely buy the same null at real API + infra cost (~32 app containers, Gmail/GitHub/Canvas
   accounts, ~$170–1.8K/pass).
2. **The one prize Toolathlon uniquely offers is the THIRD-PARTY oracle**, and a replay captures it
   for ~$0. Every EOG number is self-graded inside this repo (referee reporting to a contestant —
   the exact problem the DOS thesis is about). Toolathlon's independent verifier is what EOG
   structurally cannot be. The detectors are pure `classify…(frozen-datum, policy)` — **the
   trajectory IS their input**, so we can score them against an oracle we don't own without
   spending a dollar.
3. **The honest deliverable is PURCHASE, not LIFT.** A frozen trajectory had no intervention, so
   there is no lift number — and that boundary, stated up front, is the result, not a limitation.

So: replay the published trajectories; fold `dangling_intent` + `tool_stream`; join each fire to
the third-party `task_status.evaluation`; report fire-rate + **oracle-confirmed precision** (of
fires, the fraction the verifier scored FAILED) + lift-over-base (precision − corpus failure rate;
>0 = real skill). DETECT, measured against a clean oracle, at zero cost.

## 3. The harness (`benchmark/toolathlon/`, SHIPPED)

A CONSUMER of the kernel (it `import dos`; nothing under `src/dos/` imports it — the one-way arrow),
four pure-core-plus-boundary modules mirroring the `dos` idiom:

| Module | Role | Purity |
|---|---|---|
| `trajectory.py` | boundary READER: a raw record → frozen `StopEvidence` / `ToolStream` | pure given the dict |
| `replay.py` | the SCORER: fold both detectors, join to the label, accumulate the confusion grid | pure over parsed trajectories |
| `dataset.py` | the ONLY I/O: download + stream the JSONL | network/disk at the edge |
| `run_replay.py` | the CLI: `--files`/`--all`/`--limit`/`--by-model`/`--out` | thin shell |

Key reader decisions (each pinned by a test, `tests/test_toolathlon_replay.py`, 15 green):

- **`dangling_intent`**: `final_turn_text` = the last assistant message that authored non-empty
  text; `results_after_turn` = ENV-authored tool results after it, **excluding local-noop tools**
  (`claim_done`, sleep, context/history mgmt) — a `claim_done` ack is not an act on the world, so
  counting it would mask the very premature-stop we target.
- **`tool_stream`**: each assistant `tool_calls[i]` paired with its answering `tool` message by
  `tool_call_id` → `StreamStep(tool_name, args_digest, result_digest)`. The replay folds
  `classify_stream` over every growing prefix and keeps the PEAK state (a mid-run stall is caught
  even if the run later recovers — the live turn-by-turn semantics, evaluated offline).
- **The label**: `task_status.evaluation` ∈ {true, false}; **None excluded** from precision (never
  guessed — the un-forgeable oracle DOS does not own).

**The `result_digest` normalizer (SHIPPED — §4).** `tool_stream`'s `result_digest` originally
digested RAW result bytes, so volatile SaaS fields (timestamps, request-ids) made two
semantically-identical re-reads digest differently → an UNDER-count of true repeats. The default now
**masks** those volatile token shapes before hashing (`trajectory.normalize_result_bytes`;
`--raw-digest` for the raw floor), recovering +49 real repeats (recall 1.9%→2.9%, precision
84.9%→88.2%) — see §4 for the measured effect and the honest "it lifted recall, not false alarms"
finding. It stays byte-clean (masks ENV-authored bytes by a fixed rule the agent cannot influence,
adversarially verified). The fire-rate remains a (tighter) **LOWER BOUND** — app-specific volatile
fields with no pattern are still uncaught.

## 4. The result (VERIFIED — full corpus, 22 models, 4 figures)

**Full corpus — 66 files (22 models × 3 runs), 7,116 records, 6,862 labeled**, `--ts-min-state
REPEATING`, `result_digest` NORMALIZED (the default; see "the normalizer" below)
(`benchmark/toolathlon/_results/replay_all.json`):

```
dangling_intent  fire= 1.5%  prec=98.0%  (base=76.2%)  lift=+21.9%  recall=1.9%  falarm=0.1%  [fired=102 fail/pass=100/2]
tool_stream      fire= 2.5%  prec=88.2%  (base=76.2%)  lift=+12.0%  recall=2.9%  falarm=1.2%  [fired=170 fail/pass=150/20]
```

**The headline, plainly:** across 6,862 runs scored by an oracle DOS does not own, when
`dangling_intent` fires it is right **98%** of the time (100/102 fires were genuine third-party
failures; +21.9pp over the 76.2% base) and when `tool_stream` fires it is right **88%** of the time
(+12.0pp), at a near-zero false-alarm rate (0.1% / 1.2%). **But recall is ~2–3%** — the detectors
catch only the honest-narrating / visible-looping slice; the silent stopper (the majority of the
24% of runs that fail) is invisible to a byte-clean advisory detector, exactly as
`dangling_intent`'s forgeable-by-suppression hole predicts.

> **Do not cite the headline without the per-model figures next to it.** The corpus number is a
> capability-weighted average; the honest picture is per-model (the figures below). The single most
> misleading thing one could do is quote "98% precision / +21.9pp lift" as a flat result — it is
> true *and* it averages over 22 models, most of which fired ZERO times.

### The four figures (`benchmark/toolathlon/_results/fig{1-4}_*.png`, regenerated by `viz.py`)

- **`fig1_purchase_vs_capability`** — THE headline. Detector fire-rate (left) and precision-lift
  (right) vs model capability (x = Toolathlon task pass-rate, the in-data capability proxy from the
  SAME third-party oracle). Both detectors' fire-rate trends DOWN to ≈0 as capability rises; the
  loudest fires are on the weak models (minimax-m2 17%, gemini-2.5-flash 5%); the frontier models
  (claude-4.5-sonnet-0929, gpt-5.1, gemini-3-pro, deepseek-3.2-thinking) fire **0**. Purchase
  vanishes exactly where lift would be leaderboard-citable.
- **`fig2_per_model_grid`** — the table the headline averages over: per-model fire / precision /
  false-alarm / lift bars, models ordered least→most capable. A grey tick = the detector never
  fired (precision/lift undefined, not zero). Reads off directly: `tool_stream`'s false-alarm
  spikes on grok-4 (10.1%), o4-mini (8.3%), gemini-2.5-flash (8.3%) — the residual the normalizer
  does NOT fix (see below).
- **`fig3_simpson`** — the Simpson's-paradox view: cumulative pooled precision & lift as models are
  folded in most-fires-first. The load-bearing finding: **`dangling_intent` precision is pinned at
  ~98% from the FIRST model** (so precision is NOT fragile), but **90% of all fires come from just
  5 models** (`tool_stream`: from 10). The concentration is in RECALL/fire-mass, not precision —
  the corpus precision is honest, but it is established by a handful of broken models.
- **`fig4_confusion`** — the corpus confusion squares. The FN cell dominates (5,128 missed failures
  vs 100 caught for `dangling_intent`): high precision, ~2–3% recall, third-party-confirmed. This
  is the EOG ceiling, reproduced on a public benchmark — impossible to spin as anything but
  low-recall.

### What this says, precisely

- **PURCHASE is real but RECALL is tiny.** When the detectors fire, they fire on failures
  (precision 88–98%, lift +12/+22pp over base) — against an oracle DOS does not own. That is the
  citable, on-thesis result: byte-clean DOS detectors, scored by a third party, fire on real
  failures across model families.
- **The narrating/looping-subset CEILING holds, on a public benchmark.** The detectors catch only
  the HONEST premature stop (the agent SAYS "I still need to…") and the VISIBLE loop (the env
  returns identical bytes); they are blind to the SILENT stopper (the majority of failures) —
  exactly the forgeable-by-suppression hole `dangling_intent` names, and exactly the EOG recall
  ceiling, now reproduced externally.
- **Purchase VANISHES on the strongest model.** claude-4.5-sonnet-0929 / gpt-5.1 / gemini-3-pro /
  deepseek-3.2-thinking: **0 fires.** The strong model fails QUIETLY (no narrated obligation, no
  identical-byte loop) — the detect signal is weakest exactly where the leaderboard lives. This is
  the EOG "arg_provenance vanishes on a strong model" result, re-aimed onto the mint-INDEPENDENT
  detectors and confirmed on a public benchmark.

### The `result_digest` normalizer (the §4 lift — SHIPPED, with an honest surprise)

`tool_stream`'s `result_digest` originally digested RAW result bytes, so a stall where each re-read
carried a fresh volatile field (an ISO timestamp, a UUID, a PDF `D:…` date, a pdf-tools `Search ID`)
digested DIFFERENTLY and read as ADVANCING — UNDER-counting true repeats. `trajectory.normalize_result_bytes`
(default-on; `--raw-digest` for the floor) masks those volatile token shapes to a fixed sentinel
before hashing. Measured effect, raw→normalized over the full corpus:

```
tool_stream  RAW (--raw-digest):  fire 1.7%  prec 84.9%  lift +8.7%  recall 1.9%  [fired_fail 101, fired_pass 18]
tool_stream  NORMALIZED (default): fire 2.5%  prec 88.2%  lift +12.0% recall 2.9%  [fired_fail 150, fired_pass 20]
```

**The honest surprise (recorded, not hidden):** the normalizer's dominant effect was **RECALL, not
false-alarm cleaning.** It recovered **+49 real repeats** (fired_fail 101→150) the volatile churn
hid, lifting recall 1.9%→2.9% and precision 84.9%→88.2%. The +49 landed **100% on oracle-FAILED
runs** (verified byte-exact: `oracle_failed`/`oracle_passed` denominators are fixed raw→norm, so this
is genuine recall, not a denominator-shift illusion), spread across 7 models (grok-4 +15,
grok-code-fast-1 +13, grok-4-fast +10, kimi-k2 +4, gpt-5-mini +3, o3 +2, o4-mini +2). But **false
alarms barely moved (18→20, +2)** — and the per-model false-alarm spikes (grok-4 10.1%, o4-mini
8.3%, gemini-2.5-flash 8.3%) are **byte-identical** between raw and normalized. So those spikes are a
DIFFERENT phenomenon — genuine identical-result polling on tasks that nonetheless PASSED (the named
honest hole: eventual-consistency re-reads that were legitimate, which is exactly why the
intervention on REPEATING must be a turn-preserving WARN, never a cut). The first-pass hypothesis
("the normalizer should kill the false alarms") was **wrong**; the data says it raises recall and
leaves the false alarms — a separate, content-level phenomenon — intact.

> **Honest caveat (adversarial-verify finding):** the +2 new false alarms are not corpus-spread —
> they landed on exactly **two previously-clean models, glm-4.6 (precision 1.0→0.75) and o3
> (1.0→0.857)**, a small per-model precision regression normalization introduced where the raw floor
> had none. It is dominated by the +49 recall gain, but it is a real cost, named here rather than
> averaged away.

**Why the normalizer stays byte-clean (§5a preserved — adversarially verified).** It masks
ENV-authored bytes (the gym MCP server's result) by a FIXED, content-blind rule the agent cannot
influence — so the masked digest is still an env-authored identity, and the §5a line ("the agent did
not author the identity of its repeated output") holds verbatim. Two independent skeptics confirmed
both forgery directions fail: (1) **false-ADVANCING** (suppressing a real stall) is *structurally
impossible* — masking is `re.sub` to a fixed sentinel, which only removes variation, so two
genuinely-identical results always normalize identically; (2) **false-REPEATING** confers no agent
benefit — the verdict is advisory (a turn-preserving WARN that re-surfaces a held value, never a
cut), and precision is scored against the third-party label the agent cannot move. The masking is
deliberately CONSERVATIVE and anchored to volatile token *shapes*: masking two timestamps to `<TS>`
collapses two TIMES, but two results differing in real payload still differ — so it can only ADD
recall, never MANUFACTURE a false REPEATING from genuinely-advancing rows (pinned by
`test_normalizer_does_not_manufacture_a_repeat_from_advancing_rows`).

> **The residual over-mask hole, named (adversarial-verify finding):** an over-mask *can* occur if an
> env result's ENTIRE distinguishing payload sits inside a masked token shape (e.g. a result whose
> only content is a bare UUID answer → `<UUID>`), collapsing two genuinely-different env outputs to
> one digest → a false REPEATING. It is **env-driven, not agent-forgeable** (the agent does not
> author which bytes the env stamps), confers **no benefit** (REPEATING → harmless re-surface WARN),
> and the common cases are pinned shut by tight anchoring — but it is a *mitigation by
> pattern-tightness, not a proof of zero collapse.* The loosest pattern is `<ETAG>` (a greedy capture
> after `etag=`); a future hardening is to tighten it or drop it (it is the rarest, 0.1%).

> **Phase 2 REMAINING (next agent):** the fail-by-failure-mode breakdown (join the fires to the
> paper's §5 taxonomy). The durable rows + `schema.md` + the 4 figures are committed under
> `benchmark/toolathlon/_results/`. **Phase 4 (the live none-vs-WARN A/B that produces a LIFT
> number) is the move that makes this publishable — the detailed prompt is in
> `benchmark/toolathlon/HANDOFF.md`.**

## 5. The boundary (do not overclaim past this)

- **This measures DETECT, not FIX.** No intervention happened in a frozen trajectory; there is **no
  lift number** and this doc claims none. Whether a WARN re-surface would CONVERT a fired failure
  into a pass is the live-A/B question — and the EOG record predicts it is null on capable models
  (a capable model that stopped could not form the step; re-surfacing hands back the wall). Lift
  has only ever appeared on a WEAK model; Toolathlon will run one (the paper ran Gemini-2.5-Flash
  at 3.7%), but the weak model where lift could appear is NOT the strong model where lift is
  leaderboard-citable — the scissors no single run closes.
- **`verify`/`arbitrate`/`liveness`/`resume` have NULL purchase here as shipped:** single-agent on
  isolated state ⇒ no admission decision (arbitrate null by construction); no git/WAL in the loop
  ⇒ the shipped git-rung `verify`/`liveness`/`resume` are inert. Toolathlon's own
  `evaluation/main.py` IS the `verify` rung and DOS does not own it. Only the two in-flight,
  byte-clean detectors have a job.
- **`tool_stream` fire-rate is still a LOWER BOUND even with the normalizer.** The §4 normalizer
  masks the common volatile token *shapes* (timestamps/UUIDs/PDF-dates/Search-IDs/ETags) and
  recovered +49 real repeats, but it does not catch app-specific volatile fields it has no pattern
  for — so the normalized fire-rate is a tighter lower bound, not the true rate. A per-app-family
  field allow-list would tighten it further (§4).

## 6. Bottom line

Toolathlon is worth engaging — as a **free replay study reporting detect-PURCHASE against an oracle
DOS doesn't own**, not as a leaderboard-lift chase. The cleanest, most citable, most on-thesis
result available here costs $0: `dangling_intent` and `tool_stream` fire with high precision and low
recall on the strong models EOG under-exercised, and their purchase — measured against an
independent verifier — is the FIRST DOS result a third party scored. The detect/fix gap and the
strong-model recall collapse are not failures of the study; they are the honest shape of what a
byte-clean, advisory, no-planner substrate can and cannot do on a long-horizon benchmark, now shown
on a public one.
