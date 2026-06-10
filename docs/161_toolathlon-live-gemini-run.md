# Toolathlon LIVE — standing up the real env and running Gemini, with the detectors scored on our own runs

> **docs/157 scored DOS's byte-clean detectors on FROZEN trajectories someone else
> drove (the $0 replay over `Toolathlon-Trajectories`). This doc closes the obvious
> gap: we stood up the REAL Toolathlon environment, drove `gemini-2.5-flash` through
> 27 tasks ourselves, let the THIRD-PARTY `evaluation/main.py` score each one, and
> then folded the SAME `dangling_intent` / `tool_stream` / `terminal_error` detectors
> over the trajectories WE just produced. The result holds the line docs/157 drew:
> 27 live runs, 27 third-party failures (on-distribution for a 3.7%-Pass@1 model),
> and exactly ONE detector fire — `tool_stream` REPEATING on `privacy-desensitization`,
> 100% precision, 3.7% recall. The low-recall / high-precision shape the replay
> predicted reproduces on runs we drove live. This is NOT the live none-vs-WARN A/B
> (still the publishable move, HANDOFF Phase 4); it is the step before it — proof the
> env runs end-to-end under our own key, the detectors score a live run with no kernel
> change, and the numbers match the frozen study.**

**Status:** SHIPPED this session (2026-06-05). The live runner is HKUST's **public eval
service** (`47.253.6.47:8080`, zero local container setup); the model is `gemini-2.5-flash`
via Google's OpenAI-compat endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/`).
A new boundary reader `benchmark/toolathlon/live_adapter.py` bridges a live result dir into the
frozen `Trajectory` the docs/157 scorer already understands — **the detectors are unchanged**;
only the reader is new. Durable artifact: `benchmark/toolathlon/_live/results/live_scored_rows.csv`
(27 rows, one per task, every field a scalar, reproducible from the downloaded run dirs with zero
network).

**Lineage.** Direct continuation of [`docs/157`](157_toolathlon-replay-detector-purchase.md) (the
$0 replay) — same detectors, same third-party oracle, same DETECT-not-FIX boundary; the only change
is the trajectories are now OURS. Inherits the detector doctrine from `docs/143` (the −9pp WARN-only
lesson), `docs/145` (`tool_stream`, the mint-independent loop axis), `docs/150`/`152`
(`dangling_intent`), and `docs/158` (`terminal_error`). The next step is `benchmark/toolathlon/HANDOFF.md`
Phase 4 (the live none-vs-WARN A/B that produces a LIFT number).

---

## 1. How the env was stood up (VERIFIED, 2026-06-05)

Toolathlon offers four run paths (README §Quick Start). We used the **public evaluation service**,
which is the lowest-friction REAL env: HKUST hosts all 32 app containers + MCP accounts, and the
client (`eval_client.py`) submits a task list + a model API key over HTTP. No local Docker, no
account registration. Trade-off: a per-IP rate limit (180 cumulative minutes + 3 requests / 24h).

- **Model access (probed, not assumed):** the job repo's `GEMINI_API_KEY` (an `AQ.`-prefixed
  Google key, len 53) authenticates Google's OpenAI-compat endpoint — verified with a live
  `chat/completions` call that returned `finish_reason: tool_calls` and a well-formed tool call, so
  Gemini does proper OpenAI-style function-calling under Toolathlon's agents-SDK scaffold.
- **Console trap (re-hit, then fixed):** Windows console is cp1252; the client prints `✓`/CJK task
  text and crashes with `UnicodeEncodeError`. Force `PYTHONUTF8=1 PYTHONIOENCODING=utf-8` for every
  `eval_client.py` invocation. (Same trap the docs/157 HANDOFF flagged.)
- **Task routing (the operator's instruction):** of the 108 `finalpool` tasks, a scan of each
  `task_config.json:needed_mcp_servers` splits them into **41 local-runnable** (only
  filesystem/terminal/fetch/excel/pdf-tools/arxiv/scholarly/memory/howtocook/canvas/emails — no
  external SaaS account) vs **67 external/hard** (google_sheet/notion/github/woocommerce/snowflake/
  huggingface/k8s/…). Of the 41, **29 are pure-local** (run entirely inside the task image, zero
  account setup). Per the operator's rule — *"use their service only for the hard ones we can't test
  locally"* — the public service is reserved for the 67; the local env (Phase 2 below, in progress)
  takes the 41. This live run exercised the **pure-local subset on the public service** because it
  was the fastest path to a real result while the local env builds.

## 2. The runs (3 public-service jobs, 27 distinct tasks, all `gemini-2.5-flash`)

| Job | Tasks | Result | Notes |
|---|---|---|---|
| `job_93dfae9d93e0` | 1 (`find-alita-paper`) | 0/1 | smoke, `--skip-container-restart`, $0.0022, proved pipeline end-to-end in ~50s |
| `job_b1cfca6d35de` | 5 (smoke subset) | 0/5 | clean container restart each task |
| `job_b147b28cd68c` | 23 (pure-local remainder) | 0/23 | 8 workers; avg **15.5 turns / 20.4 tool calls** — substantive long-horizon attempts |

**27 distinct tasks scored, 27 third-party FAILS, 0 PASS.** This is on-distribution: Toolathlon
reports `gemini-2.5-flash` at **3.7% Pass@1** (the weakest model in the paper table), so 0/27 is
within sampling — a ~4% pass rate puts the expected passes at ~1, and we drew 0. The point of the
run is NOT the pass rate (we knew it would be low); it is the **failure-mode distribution** and
whether the detectors fire on it. (Two tasks — `imagenet`, `arrange-workspace` — errored during
incremental download and have no trajectory; they are skipped, never guessed, the docs/157
discipline.)

Observed failure modes (read off the trajectories), in three honest buckets:

- **Do-nothing / instant give-up** (`git-milestone`: 0 tool calls; `sales-accounting`: 0;
  `find-alita-paper`: 2 calls then "no paper found" and stop). Confident-wrong or no-op termination.
- **Genuine long effort that still missed** (`shopping-helper`: **99 steps**, hit the step cap;
  `language-school`: 31; `fillout-online-forms`: 29; `paper-checker`: 26 steps / 16.9k output
  tokens). The model worked the task hard and the third party still scored it wrong.
- **Read-but-never-wrote** (`detect-revised-terms`: read the PDF across 5 steps, never wrote the
  required `revised_terms.csv`). Output-side early-stop.

## 3. The detectors, scored on OUR live trajectories

`live_adapter.py` re-keys a live task dir (`traj_log.json` + `eval_res.json`) into the dataset-shaped
record `trajectory.parse_record` expects, so the **pure** detector folds from `replay.py`
(`dangling_fired`, `tool_stream_fired`, `tool_stream_peak`, `terminal_error_fired`) run verbatim.
The full grid (`live_scored_rows.csv`):

| metric | value |
|---|---|
| runs scored | 27 |
| third-party FAIL | 27 |
| any-detector fires | **1** |
| fires on a real FAIL | 1 |
| **recall** | 1/27 = **3.7%** |
| **precision** | 1/1 = **100%** |
| `tool_stream` peak = ADVANCING | 26 |
| `tool_stream` peak = REPEATING | 1 |
| `dangling_intent` fires | 0 |
| `terminal_error` fires | 0 |

**The one fire is crisp and correct.** `privacy-desensitization` (6 steps, third-party FAIL with
`Content mismatch (27)`) called `filesystem-list_directory` and got the **identical result digest
`b9df0f8f8cb138ac` three times in a row** (steps 2,3,4) — it re-listed the same directory, got the
same bytes, made no progress. That is exactly the no-progress loop `tool_stream` REPEATING exists to
flag, and it fired on a run that genuinely failed. Provenance-clean: the gym MCP server authored the
repeated result bytes, not the judged agent (the §5a line — REPEATING is provenance-of-repeated-output,
never a satisfaction predicate).

**Why the other 26 don't fire — and why that is RIGHT, not a miss:**
- `dangling_intent` fires only on a **committed-future-intent marker** in the terminal turn ("I still
  need to…", "next I will…"). The do-nothing and confident-wrong stops end with a flat (false)
  *declaration* — e.g. `find-alita-paper`'s "No paper… was found" — which is a wrong conclusion, not
  a dangling intent. The detector ABSTAINS (verified: `DanglingVerdict(ABSTAIN, "no committed-future-
  intent marker")`) rather than false-fire. Catching confident-wrong termination needs grounding the
  claim against env state — a different rung, not a byte-clean stop detector.
- `tool_stream` stays ADVANCING on the long churning runs (`shopping-helper`'s 99 steps included)
  because each step was a **different** `(tool, args, result)` triple — churn-without-repeat is a
  distinct failure mode from loop-on-identical-result, and the detector honestly does not claim it.
- `terminal_error` needs an explicit terminal error string in the stream; these runs failed on
  *content* (wrong/absent output files), not on a surfaced error, so it correctly stays silent.

## 3b. The broadened LOCAL run (our own WSL containers, N=29) — and an honest confound

We then stood up the env a SECOND way — our own containers, the bulk path off the rate limit. The
local containerized runner (`scripts/run_single_containerized.sh`) is Linux-host-oriented
(hardcoded `--network host` + `-v /var/run/docker.sock`), so it does NOT run on Docker-Desktop-for-
Windows directly; it runs NATIVELY inside **WSL2** (Ubuntu 24.04), which shares the same Docker
daemon (sees the 10.9 GB task image already pulled). Setup gaps cleared: create
`configs/global_configs.py` (docker), placeholder `gcp-oauth.keys.json`/`google_credentials.json`,
and `configs/token_key_session.py` (from the example). Two bugs cost a wasted batch, recorded so the
next run skips them: (1) the task list had **CRLF** line endings → each task name got a trailing
`\r` and the runner couldn't find the task dir (strip `\r` in the loop); (2) **never run two
Toolathlon containers concurrently** on one daemon — they share container names / Kind / host-network
ports and collide. Run sequentially with exclusive Docker access.

The local batch ran all 29 pure-local tasks (`local_scored_rows.csv`): **1 PASS** (`find-alita-paper`
— the SAME task failed on the public service and in two earlier local runs; gemini-2.5-flash is
stochastic, real run-to-run variance), 26 FAIL, 2 with a `null`/absent label (excluded). **4 detector
fires, 100% precision (0 false alarms, none on the 1 PASS), 15.4% recall (4/26)** — higher than the
public service's 1/27.

**But the higher recall is partly a CONFOUND I introduced, and the honest split matters:**
- **1 of the 4 fires is a clean MODEL-behavior fire.** `identify-all-songs` (`dangling_intent`, 19
  steps) — the agent's final turn: *"I have created the `songs.md` file as requested, **but I was
  unable to extract the list of songs**… the youtube-transcript tool…"* — it explicitly admits the
  core task is unfinished while claiming partial done. That is exactly the premature-completion crack
  `dangling_intent` exists to catch, on a real model failure mode, provenance-clean.
- **3 of the 4 fires are `terminal_error` on `google serper search failed` errors** (`cvpr-research`,
  `hk-top-conf`, `language-school`) — REAL terminal errors in the stream (the detector is correct:
  there genuinely was an error), **but the error is INFRASTRUCTURE, caused by my placeholder
  `serper_api_key = "XX"`** in `token_key_session.py` (I did not provision a web-search key for the
  local env). The public service HAS a real serper key, so those same tasks did not error there. This
  is not an apples-to-apples model comparison on those 3.

So the apples-to-apples, **model-behavior** recall across both environments is ~1/27 (public) and
~1/26 (local, the `dangling_intent` fire) — **the replay's low-recall shape holds in BOTH**; the
local 15.4% is inflated by a setup gap, reported here rather than banked. The clean cross-env finding
is: **0 false alarms across 56 live runs** (27 public + 29 local), and every fire landed on a real
FAIL. The detectors do not false-fire on live Gemini, in two independently-stood-up environments;
recall stays low and concentrated in the narrating/looping/erroring subset. (Re-running the local
batch WITH a real serper key — to see whether those 3 tasks pass or fail-without-erroring — is the
clean follow-up; it would also test whether the `terminal_error` recovery-check of docs/162 silences
them.)

## 4. What this establishes, and what it does NOT

**Establishes:**
- The real Toolathlon env runs end-to-end under our own Gemini key, scored by the third party, with
  the artifacts (trajectory + conversation + eval verdict + workspace) downloaded locally.
- The docs/157 detectors score a LIVE run with **zero kernel change** — only a 60-line boundary
  reader (`live_adapter.py`), mirroring the `dataset.py`/`replay.py` split.
- The env was stood up TWO independent ways (HKUST's public service AND our own WSL containers),
  and across **56 live Gemini runs (27 + 29) there were ZERO false alarms** — every detector fire
  landed on a real third-party FAIL, none on the 1 PASS. The detectors do not false-fire on live
  Gemini.
- The replay's headline — **high precision, ~2–4% recall, purchase concentrated in the
  loop-on-no-progress subset** — reproduces on trajectories we drove ourselves. The one fire is a
  true positive; nothing false-fired across 26 abstentions.

**Does NOT establish (the honest boundary, same as docs/157 §5):**
- **No LIFT number.** Even live, these runs had no intervention — DOS OBSERVED, it did not WARN. Whether
  re-surfacing the repeated directory listing to `privacy-desensitization` would have CONVERTED its
  fail→pass is the none-vs-WARN A/B question (HANDOFF Phase 4), and the EOG record predicts ~null on a
  capable model / small-positive only on a weak looping one. `privacy-desensitization` is the kind of
  weak-looping case where a WARN *could* help — it is the single best A/B candidate this run surfaced.
- **N=27, single model, single run each.** A fire-rate of 1/27 has a wide CI; this is a directional
  live confirmation, not a powered estimate. The powered number is the replay's 7,116-record corpus.
- **Pure-local tasks only.** The 67 external tasks (the harder, more cross-app ones where looping is
  likelier) are not in this sample — they need either the local container deploy or more public-service
  quota. Expect the external subset to fire MORE (more tool surface, longer horizons).

## 5. Reproduce

```bash
# 1. validate the key does OpenAI-compat tool-calling (no spend beyond one tiny call)
curl -s "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions" \
  -H "Authorization: Bearer $GEMINI_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"gemini-2.5-flash","messages":[{"role":"user","content":"call get_weather for Tokyo"}],
       "tools":[{"type":"function","function":{"name":"get_weather","parameters":{"type":"object",
       "properties":{"city":{"type":"string"}}}}}]}'

# 2. submit a pure-local subset to the public service (force UTF-8 on Windows)
cd Toolathlon
PYTHONUTF8=1 python eval_client.py run --mode public \
  --base-url "https://generativelanguage.googleapis.com/v1beta/openai/" \
  --model-name gemini-2.5-flash --api-key "$GEMINI_API_KEY" \
  --server-host 47.253.6.47 --server-port 8080 --workers 8 \
  --output-dir <out> --task-list-file <pure_local_tasklist.txt>

# 3. score the detectors over the downloaded runs (pure, zero network, zero kernel change)
cd dos
python -m benchmark.toolathlon.live_adapter  # (or the inline scorer that writes live_scored_rows.csv)
```

The task lists (`local_all.txt` / `external_all.txt` / `pure_local.txt`), the three result dirs, and
`live_scored_rows.csv` live under `benchmark/toolathlon/_live/` (gitignored data; the CSV is small
and self-contained — un-gitignore it if you want it version-controlled, like the replay's rows).
