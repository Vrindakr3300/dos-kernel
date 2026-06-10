# 125 — GHF: Go hook fast-path — break ground at the felt-latency seam

> **Status:** GHF1+GHF2(posttool)+GHF3+native-`marker`+native-`stop`+**GHF4 (the
> hooks.json flip)** SHIPPED (2026-06-09). The plugin's `hooks.json` now calls the
> BUNDLED launcher `${CLAUDE_PLUGIN_ROOT}/bin/dos-hook` (not a bare PATH name) under
> a pinned `"shell": "bash"`, so the native fast-path is the default on every OS and
> the `|| python` tail is only reached on a DELEGATE (exit 3) or a missing binary.
> The §8.3 Windows blocker dissolved: current Claude Code ships a per-command
> `"shell"` field (`bash`|`powershell`) + resolves `${CLAUDE_PLUGIN_ROOT}` before the
> shell, so pinning `bash` runs the POSIX launcher under Git Bash on Windows too (and
> the `||` parses) — no per-OS command-string split needed. The POSIX launcher was
> taught to recognise Windows-under-Git-Bash (`uname -s` = `MINGW*`/`MSYS*`/`CYGWIN*`
> → GOOS `windows`, `.exe` suffix), so it actually reaches the bundled
> `dos-hook-windows-amd64.exe` rather than falling back to Python. GHF5 (fold the hook
> deciders into the NSP/124 envelope) is the only remaining phase. The first `go/`
> module landed: `dos-hook` serves **`pretool`** and **`posttool`** natively behind
> `DOS_HOOK_NATIVE` (now default-ON), byte-exact on the decision projection vs the
> Python verbs
> (a 19-case pretool decision corpus + a 6-sequence stream-stateful posttool corpus
> + the gold live corpus, all green), pretool median ~10 ms vs ~600 ms Python (a ~60×
> felt-latency win). `pretool` OWNS every outcome natively — a passthrough emits
> nothing; a deny/warn emits the dialect AND writes the OP_ENFORCE WAL record itself
> (byte-identical to `cli._journal_pretool_outcome`). `posttool` reads+appends the
> per-session stream and emits the REPEATING/STALLED WARN (the stream record is
> byte-identical to Python's). Wired into the live plugin `hooks.json` via
> `dos-hook … || python -m dos.cli hook …` (a missing binary → exit 127 → the `||`
> runs Python, so no machine is blocked; the binary exits 3=DELEGATE for a verb it
> does not own, WITHOUT consuming stdin, so the `||` Python gets clean stdin).
> GHF3's differential gate (`tests/test_go_hook_parity.py` + `go test ./internal/hook`)
> covers both verbs. **`stop` deliberately stays Python-delegated** (exit 3 → `||`):
> it fires once per TURN (not per tool call), so the cold-start is negligible there,
> and porting its `verify()` rung hits the docs/124 §1.2 RE2 lookbehind blocker
> (`phase_shipped.py`/`stamp.py` use lookbehind) that the oracle-cluster port (GHF5/124)
> scopes — porting it now would mean rewriting that grammar RE2-compatibly for a
> surface with no felt-latency payoff. GHF4 (plugin ships the binary), GHF5 (fold into
> the NSP/124 envelope, incl. the native `stop`/`verify` rung) remain. Breaks ground on
> [`100`](100_native-spine-port-plan.md)
> (NSP) + [`124`](124_the-go-core-build-plan-and-the-parity-contract.md) (the
> Go-core build plan + parity-contract split) at the seam they de-prioritized — the
> per-tool-call HOOK hot path. Adopts 100's pure-decider boundary and 124's
> byte-exact-decision / prose-excluded parity contract VERBATIM; adds only a
> throughline-first phase order anchored on the hook seam + the concrete
> first-ground mechanics. Phases: **GHF1** Go serves `hook pretool` end-to-end
> behind `DOS_HOOK_NATIVE=1` in the live plugin path · **GHF2** `posttool` + `stop`
> on the same binary · **GHF3** differential parity gate (decision-projection
> byte-exact) over the hook deciders · **GHF4** the plugin ships the binary,
> `hooks.json` calls it directly (no Python on the hot path) · **GHF5** fold the
> hook deciders into the NSP/124 envelope ABI + corpus (converge, don't fork).

> **[`100`](100_native-spine-port-plan.md) (NSP) named the Python-cold-start
> problem and the Go boundary; [`124`](124_the-go-core-build-plan-and-the-parity-contract.md)
> split the parity contract (byte-exact decision, prose excluded);
> [`122`](122_the-core-go-runtime-and-the-on-device-kernel.md) showed the same
> binary is the on-device runtime. All three are RIGHT and all three are UNBUILT.
> This plan does not re-theorize — it BREAKS GROUND, and it picks the breaking
> point NSP explicitly de-prioritized: the HOOK hot path. NSP scoped its perf case
> on CI-storm `verify` and called the per-call loop/daemon win "too small to clear
> the bar." But the per-call win is exactly what a Claude Code operator FEELS: the
> plugin's `pretool`/`posttool` hooks fire `python -m dos.cli hook …` on EVERY tool
> call, paying ~80–150 ms interpreter cold-start × 2 (measured 0.3–0.8 s/verb live,
> 2026-06-08). That is the latency that prompted this plan. docs/122 already
> resurrected this dismissed win for the edge regime; this plan claims it for the
> desktop regime too, and uses it as the THROUGHLINE-FIRST wedge: ship the smallest
> Go-served hook that kills the felt latency, enabled in the live plugin path, then
> thicken toward the full NSP/124 contract.**

Status: BUILD plan, breaking ground on [`100`](100_native-spine-port-plan.md) +
[`124`](124_the-go-core-build-plan-and-the-parity-contract.md). Nothing here
re-decides the boundary or the parity split — those are settled in 100/124 and this
plan ADOPTS them verbatim. What it adds is a throughline-first PHASE ORDER anchored
on the hook seam, and the concrete first-ground mechanics (the Go module, the flag,
the fallback, the plugin wiring).

The positioning half — *why a fast native trust kernel is a market* — stays in
`dos-strategy` (CLAUDE.md split). This is the mechanism half.

---

## 0. Why a fourth doc, and why it leads with hooks

Three plan docs (100/124/122) circle the Go port; none broke ground. The risk they
share is the one the phased-plan ceremony names: **a plan sequenced so the feature
only comes alive at the last phase** — here, "port the whole pure core, prove full
parity, maybe ship someday." That is the stranded-at-80% trap. This plan inverts it:

- **Throughline-first.** Phase 1 ships ONE Go-served hook verb (`pretool`), enabled
  in the LIVE plugin path behind a flag, so the latency win is real and felt on day
  one — not deferred behind a full-corpus parity gate.
- **Felt-latency seam, not theoretical-storm seam.** NSP optimized `verify` under
  CI fan-out (real, but invisible to a desktop operator). The hooks are what a human
  watching their own session experiences. Same cold-start root cause; higher-felt
  surface. Picking it means the first ground we break is the one that pays back
  immediately and visibly.
- **Converge, don't fork.** Phases 1–2 may ship a hook-specific Go decider to move
  fast; Phase 5 FOLDS those deciders into the NSP/124 envelope ABI + differential
  corpus so we end with ONE Go core, not a hook silo beside an NSP silo. The plan is
  explicit that the fast path is a wedge INTO 100/124, not a competitor to it.

## 1. The measured problem (grounding, 2026-06-08)

| Surface | Measured | Notes |
|---|---|---|
| bare `python` startup | 0.001 s | interpreter itself is not the issue in isolation |
| `import dos` | 0.22 s | dominated by `_hashlib` (85 ms) + `dos.lane_journal` (46 ms) |
| `dos doctor` end-to-end | 0.89 s | one-shot CLI call |
| **`dos hook pretool`** | **0.3–0.8 s/call** | **fires on EVERY tool call (PreToolUse)** |
| **`dos hook posttool`** | **0.3–0.8 s/call** | **fires on Read\|Bash\|Grep\|Glob (PostToolUse)** |

A single tool call pays the PreToolUse hook + (often) the PostToolUse hook = up to
~1.6 s of Python cold-start wrapped around it, on top of the host repo's own hook
stack. The dos LOGIC inside each hook is cheap (predicate eval, stream classify);
the cost is **interpreter + import**, exactly the cost a static Go binary erases.

Hot-path facts a Go binary must honor (from the docs/100 + cli.py audit):
- `cmd_hook_pretool` (cli.py ~4127–4227): Rung A `admission.run_predicates()` over
  (tree, live_leases); Rung B `arg_provenance.classify_call()`; emit CC PreToolUse
  JSON; best-effort journal. Touches `lane_lease` WAL read + `config` load.
- `cmd_hook_posttool` (cli.py ~3987–4125): build StreamStep, read prior stream,
  `tool_stream.classify_stream()`, append to accumulator WAL; emit CC PostToolUse.
- `cmd_hook_stop` (cli.py ~3845–3987): `claim_extract` + `verify()` per claim vs
  git; emit CC Stop block/passthrough.

## 2. What this plan ADOPTS unchanged from 100/124 (no re-decision)

1. **The boundary** (NSP): Go is a PURE decider. It receives resolved config +
   gathered evidence as JSON on stdin; it never reads the disk, git, or the clock.
   I/O (config load, WAL read/write, git, stream-accumulator file) stays Python —
   OR, where a hook needs I/O the Python wrapper can't pre-gather, the Go binary
   shells the SAME evidence-gathering the Python path uses (see §4 seam note).
2. **The parity-contract split** (124 §2): the differential gate is BYTE-EXACT over
   the decision-bearing projection; the `reason` prose is carried but NOT gated.
   Default (124-A): Go returns decision fields + a structured reason CODE +
   integer/rational operands; Python renders the human prose. The float never
   crosses into Go.
3. **The fallback discipline** (NSP): Python stays the always-available fallback AND
   the differential oracle. The flag (`DOS_HOOK_NATIVE=1`, this plan's analogue of
   `DOS_SPINE_NATIVE`) selects the Go path; absent/0/binary-missing → Python, byte
   for byte as today. Fail-safe is unchanged: any error → emit nothing, exit 0.

## 3. The throughline-first phase order

### GHF1 — `pretool` served by Go, end-to-end, in the live plugin path
The smallest end-to-end slice, ENABLED where it's felt.
- New Go module `go/` in the dos repo (first Go in this repo — see §4). One binary,
  `dos-hook`, one subcommand `pretool`.
- Go reads the CC PreToolUse event on stdin, computes the pretool decision over the
  decision-bearing inputs it can derive WITHOUT heavy I/O (the structural PRE-marker
  check + tree extraction + the disjointness/self-modify predicates over leases
  passed in). For the lease set, GHF1 accepts the cheap correct floor: the Python
  wrapper (or a tiny Go WAL reader — decided in §4) supplies `live_leases`.
- Behind `DOS_HOOK_NATIVE=1`: `hooks.json`'s pretool command becomes a thin shim
  that runs the Go binary when the flag+binary are present, else the Python verb.
- **Throughline proof (GHF1 exit):** with the flag on, a tool call's PreToolUse hook
  is served by Go in < 30 ms (vs 300–800 ms), the emitted JSON is byte-identical to
  the Python verb's on a hand corpus of N events, and the advisory/deny behavior
  (the "DOS PRE-admission" reminder) is unchanged. Measured before/after, recorded
  in `docs/baselines.yaml`.

### GHF2 — `posttool` + `stop` on the same binary
Thicken to all three hook verbs.
- `dos-hook posttool`: StreamStep build + `classify_stream` port; the stream
  accumulator read/append is the I/O seam (§4).
- `dos-hook stop`: `claim_extract` + the `verify` decision. NOTE `verify` needs git
  — this is the one hook with an unavoidable git shell. GHF2 keeps that git call in
  the evidence-gathering layer (Python pre-gathers the claim→ancestry facts, OR the
  Go binary shells `git` directly with the SAME grammar; §4 picks). The DECIDER
  stays pure.
- Exit: all three hook verbs served by Go behind the flag, each byte-parity on the
  decision projection over its hand corpus, each < 30 ms decider time.

### GHF3 — differential parity gate over the hook deciders
Make the parity a CI ratchet, not a one-off check.
- Per 124 §2/§3 Phase-0 shape, but scoped to the THREE hook deciders: export a
  corpus of (pretool|posttool|stop) events → for each, the canonical decision
  projection (byte-gated) + the full struct incl. reason (logged, advisory diff).
  A cross-engine replay asserts byte-equality on the projection; reason diffs log
  without failing.
- Negative test (124 Phase-0 add): two events identical in decision, different in
  reason prose → projection equal, gate green. Proves the projection excludes prose.
- Exit: `pytest`/`go test` cross-replay green on the hook corpus; the gate fails
  loudly on an injected decision drift, stays green on an injected prose-only drift.

### GHF4 — the plugin SHIPS the binary; hooks.json calls it directly
Close the throughline: no Python on the hot path at all.
- `scripts/build_plugin.py` (or a sibling) builds/embeds the `dos-hook` binary for
  the host arch into the plugin bundle, or `dos init --hooks` drops it.
- `hooks.json` calls the binary directly (with the Python verb as the documented
  fallback for an arch with no prebuilt binary). The `DOS_HOOK_NATIVE` flag becomes
  default-on where the binary is present.
- Exit: a fresh plugin install on a supported arch pays ZERO Python cold-start on
  tool calls; the clean-room test (the docs/_packaging stranger path) shows the
  per-call hook tax gone. Fallback still works where no binary ships.

### GHF5 — converge into the NSP/124 core (don't leave a hook silo)
End with ONE Go core.
- Fold the three hook deciders into the NSP/124 envelope ABI (124 §4) and the shared
  differential corpus, so the hook fast-path and the (future) `verify`/`arbitrate`/
  `gate` native deciders are the SAME binary + the SAME parity gate, not parallel
  forks. This is the seam that makes GHF a wedge into 100/124 rather than a detour.
- Exit: the hook deciders live behind the NSP envelope; building the NSP `arbitrate`
  decider reuses GHF's `admission`/`lane_overlap` port (GHF1 already needed it).
  docs/100 Phase order can then proceed with the hook seam already native.

## 4. First-ground mechanics (the concrete unknowns to settle in GHF1)

- **First Go in the dos repo.** A `go/` module (module path TBD, e.g.
  `github.com/anthony-chaudhary/dos-kernel/go`), Go 1.25 to match the job repo's
  toolchain. Static build, no cgo, so it cross-compiles (the docs/122 device payoff
  comes free later).
- **The I/O seam decision (the load-bearing GHF1 choice).** Two honest options, pick
  in GHF1 with a measured spike:
  - **(S1) Python pre-gathers, Go decides.** The hooks.json shim stays a 2-line
    Python that loads config + reads leases, then pipes a resolved-evidence JSON to
    the Go decider. SIMPLE and keeps the boundary pure — BUT it still pays SOME
    Python cold-start (just less, if the gathering is lighter than the full hook).
    Measure whether "light Python gather + Go decide" actually beats today; if the
    gather still imports `config`+`lane_journal` (the 46 ms + heavy bits), the win
    may be small — which pushes to S2.
  - **(S2) Go reads the WAL + config too.** Port the NARROW readers the hooks need
    (the `dos.toml [lanes]` parse + the lane-journal WAL line format) into Go, so the
    binary is self-contained and pays NO Python. More work + reintroduces the
    "reimplement file-format semantics in Go" hazard NSP warned about — CONTAINED
    here because the hook readers are a tiny, stable subset (lane trees + live-lease
    lines), gated by the same differential corpus. This is almost certainly the real
    answer for the felt-latency win; GHF1 proves it on `pretool` only.
  - Decision rule: GHF1 ships whichever HITS < 30 ms end-to-end on `pretool`. If S1
    can't (because the Python gather still cold-starts), GHF1 ships S2 for the lane
    read and documents the contained file-format-parity risk + its corpus coverage.
- **The flag + fallback.** `DOS_HOOK_NATIVE` (1/0/unset). Unset or 0 or binary-absent
  or any Go error → the existing Python verb, unchanged. This is the docs/100
  fallback discipline; the hook fail-safe (emit nothing, exit 0) sits OUTSIDE the
  flag so a Go crash can never break a turn.

## 5. Non-goals

- **Not the whole kernel.** Only the three hook deciders (+ the narrow readers they
  need). `verify`/`arbitrate`/`gate`/loop native deciders are NSP/124's scope; GHF5
  converges INTO that, it does not pre-empt it.
- **Not the CLI/TUI/MCP/renderers/drivers** (NSP non-goal, inherited).
- **Not reason-prose byte-parity** (124 non-goal, inherited): decision projection is
  gated, prose is carried.
- **Not a new boundary or contract.** GHF re-uses 100's boundary and 124's split
  verbatim; if a tension surfaces, the fix lands in 100/124, not a fifth doc.

## 6. Risk register (delta over 124 §7)

- **R1 — S2 file-format parity (the WAL/lanes readers in Go drift from Python).**
  Mitigated by the GHF3 differential corpus covering the reader output, same ratchet
  as the deciders. Contained because the subset is tiny + stable.
- **R2 — the fast path forks from NSP and never reconverges.** Mitigated by making
  GHF5 (fold into the envelope ABI) a REQUIRED phase, not optional, and by GHF1
  already porting `admission`/`lane_overlap` (which NSP's `arbitrate` phase reuses) —
  so convergence is the cheap path, not a rewrite.
- **R3 — per-arch binary shipping (GHF4) balloons the plugin.** Mitigated by the
  Python fallback: the plugin ships binaries for the common arches (win/mac/linux
  x64+arm64) and falls back to the Python verb elsewhere; no arch is BLOCKED, only
  un-accelerated.
- **R4 — the felt win is smaller than measured if the host's OWN hook stack
  dominates.** (The job repo already runs ~5 Python hooks per call.) Mitigated:
  GHF's win is per-DOS-hook and additive; it doesn't fix the host's hooks, but it
  removes DOS's 2 of the ~7, measured in the GHF1/GHF4 before/after.

## 7. Throughline check (the ceremony gate)

- Phase 1 ships the smallest END-TO-END slice (Go-served `pretool`) ENABLED in the
  live plugin path — the feature is alive at phase 1, not phase 5. ✓
- Each later phase thickens the SAME working slice (more verbs → parity gate →
  ship-the-binary → converge), never "comes alive at the end." ✓
- TOMB-eligible the moment GHF4 ships + a CI parity invariant (GHF3) is attached —
  GHF5 is convergence/close-out, not a buried soak. ✓
- `/release` runs on the user-visible code phases (GHF1/2/4 ship code; GHF3 is a
  test gate; GHF5 is a refactor) per the ceremony. ✓
- GH umbrella issue: pending phases as `- [ ]` at the dos repo's issue tracker.

## 8. Leave-off / handoff (2026-06-09) — what is LANDED, what is NEXT

> **Read this before touching `go/`.** Three commits landed GHF1+GHF2(posttool)+GHF3
> and the GHF4 *groundwork*. The remaining work is **native `stop`** (a large oracle
> port) and the **final hooks.json flip** (blocked on native `stop` + a Windows
> shell problem). Everything below is the exact state + the next moves.

### 8.1 What is LANDED (committed on `master`)

| Commit | What |
|---|---|
| `48a9093` | GHF1: `dos-hook pretool` native, byte-exact, ~60× (the `go/` module + GHF3 gate). |
| `69e24ce` | GHF2: `dos-hook posttool` native (tool_stream fold + stream accumulator); fixed a GHF1 packaging bug (`go/.gitignore` `dos-hook` matched the `cmd/dos-hook/` dir → `main.go` was never committed; anchored to `/dos-hook`). |
| `5698786` | GHF4 groundwork: `scripts/build_hook_binary.py` (cross-compile, no-cgo), `claude-plugin/bin/{dos-hook,dos-hook.ps1}` launchers, `bin/.gitignore`, and the `DOS_HOOK_NATIVE` default-ON flip in `main.go`. INERT (hooks.json not yet pointed at the launcher). |
| `25428de` | GHF4 flip: `hooks.json` calls the bundled `${CLAUDE_PLUGIN_ROOT}/bin/dos-hook` launcher directly (the "reverted" note in §8.3 below is itself stale — the flip was re-landed). |

> **GHF4 COMPLETED (2026-06-09) — the binaries are now BUNDLED in git.** The earlier
> groundwork (`5698786`) deliberately *gitignored* the per-arch binaries, on the
> "no-committed-binary" discipline + "built at /release time." But the plugin ships
> as its git tree (`marketplace.json` `source: ./claude-plugin`) and NO release/CI
> step ever built+published them — so a marketplace install (a clone) got ZERO
> binaries and silently fell back to Python on every tool call, defeating the whole
> fast-path. The fix reverses that decision: the full **amd64 + arm64 × linux/macOS/
> windows** matrix (6 binaries, `windows/arm64` added) is now **committed** into
> `claude-plugin/bin/`, so the install is direct. Pinned by
> `tests/test_hook_binaries_bundled.py` (present + tracked + not-ignored + grid
> coverage); rebuilt at `/release` Step 5.5 when `go/` changes. R3 (plugin balloons)
> is accepted (~24 MB, reproducible `-trimpath` build → byte-identical on an
> unchanged `go/`). This closes GHF4's exit criterion: "a fresh plugin install on a
> supported arch pays ZERO Python cold-start."

**Native + byte-exact today:** `pretool` (passthrough emits nothing; deny/warn emit
the dialect AND write the OP_ENFORCE WAL record itself) and `posttool` (REPEATING/
STALLED WARN + the schema-tagged stream record). Both verified against the live
Python verb (a 19-case pretool corpus + a 6-sequence posttool corpus, both
regenerated + gated by `tests/test_go_hook_parity.py`; plus a live 5-step run).
Latency: pretool ~10 ms vs ~600 ms Python.

**`stop` is NOT native** — it exits 3 (DELEGATE) and the committed hooks.json `||`
runs Python. **hooks.json is the GHF1/GHF2 baseline** (`dos-hook <verb> … || python
-m dos.cli hook <verb> …`, bare `dos-hook` name) — the `${CLAUDE_PLUGIN_ROOT}` flip
was reverted (see 8.3).

### 8.2 NEXT — native `stop` (the user's directive: all three verbs native, no Python)

`stop` needs `verify()`, which is the kernel's biggest single surface. It is a
**faithful, byte-exact port** of `oracle.is_shipped` + `phase_shipped`'s grep rung,
gated against the live Python via a verify differential corpus (the same discipline
as pretool/posttool). Map of what to port (read these in order):

1. **`claim_extract.py`** — DONE-portable (no lookbehind). Port `extract_claims`
   (the MARKER `DOS-CLAIM:` regex + the abstaining heuristic) + the frontmatter rung
   + `assistant_text_from_transcript` (JSONL tail read of the last N assistant
   turns). All RE2-compatible.
2. **`cmd_hook_stop` (cli.py ~3845–3985)** — the orchestration: read event,
   anti-loop guard (`stop_hook_active`), gather claims (frontmatter flags +
   transcript), `oracle.is_shipped` each, block on a NOT_SHIPPED *confident* claim →
   `{"decision":"block","reason":…}` at exit 0 (CC's "keep working" signal), else
   nothing. Every failure → let-it-stop. `--strict` also blocks on heuristic claims.
3. **`oracle.is_shipped` (oracle.py, ~1400 lines)** — registry-first then grep. On a
   repo with NO `execution-state.yaml` (the no-plan contract, THIS repo) it is purely
   the grep rung. Layers to port: the `recently_completed` YAML registry read; the
   grep fallback; the soak / release-bump / plan-collision DEMOTIONS (`#326`/`#399`/
   FQ-390 — all gate-OFF when their inputs are absent, so the no-plan path skips them).
4. **`phase_shipped.py` (~1500 lines) — THE HARD PART.** The git-log grep with 6
   rungs (`direct` / `release-prefix` / `body-mention` / `hyg-slug` /
   `sub-phase-parent` / `file-path` artifact), the bookkeeping-subject EXCLUSIONS
   (`_is_bookkeeping_subject`), per-workspace stamp grammar (`dos.stamp`), and the
   generic-`Phase N`-vs-series-prefixed token handling. **The ONE RE2 blocker is
   `_BOUNDARY_PRE_NEG = r"(?<![A-Za-z0-9.\-])"`** (phase_shipped.py:201) — a
   fixed-width negative lookbehind. RE2 rewrite: replace `(?<![A-Za-z0-9.\-])TOKEN`
   with `(?:^|[^A-Za-z0-9.\-])TOKEN` and adjust the match offset (standard transform;
   `stamp.py`/`enumerate.py`/`drivers/memory_recall.py` also have lookbehind but are
   NOT on the stop path). Pin every rung against the live oracle.

**Method (do NOT skip the corpus):** generate a verify differential corpus from this
repo's REAL git history — for many `(plan, phase)` pairs (real shipped phases, real
unshipped, bookkeeping subjects, release commits), record `oracle.is_shipped(...,
cfg)`'s `(shipped, source, rung, sha)`. A Go `verify_test.go` replays each against
the native verify and asserts equality. A subtly-wrong verify BLOCKS a legitimate
stop (a turn-killing regression) — the corpus is the only thing that makes this
safe. Build it INCREMENTALLY: port `direct` first (covers most), corpus-gate, then
each rung, watching the gate stay green.

⚠ **Empirical scoping first:** before porting all 6 rungs, run the live oracle over
this repo's recent commits and COUNT which rungs actually fire (the probe that was
about to run when this was paused: `oracle.is_shipped` over a sample of real
`(plan,phase)` + `git log` subjects). If `direct` + `body-mention` cover ~all real
ships here, port those two + the bookkeeping exclusion first and corpus-gate the
rest as ABSTAIN-to-Python until ported. (This repo's claims live in commit subjects,
not a registry — see CLAUDE.md "DOS on DOS" step 6.)

### 8.2.1 — Scoping RESULT (probe ran 2026-06-09; `go/internal/hook/parity/probe_verify_rungs.py`)

The probe ran the LIVE `oracle.is_shipped(plan, phase, cfg)` over a harvest of this
repo's real `docs/<NN>: <PHASE>` git-log subjects + the CLAUDE.md examples. The
result is **sharper than the handoff guessed — only ONE rung fires:**

| Rung | Real ships resolved here |
|---|---|
| `direct` | **8 / 8** (every SHIPPED verdict) |
| `release-prefix` / `body-mention` / `hyg-slug` / `sub-phase-parent` / `file-path` | **0** |

`source` grades seen: `grep-subject` (every ship) and `none` (every miss). No
`registry` (no `execution-state.yaml`), no `grep-artifact` (the file-path rung never
fired on a real ship).

**Why so few rungs are live here — this repo uses the fully GENERIC `StampConvention`**
(`dos.toml [stamp]` declares only `style="grep"`, so every other field is the empty
default). The generic convention DISABLES, structurally:
- `progress_markers = ()` → `_is_progress_only` ALWAYS returns False (no demotion).
- `sub_phase_parent_fallback = False` → that rung never runs.
- `summary_bundle_prefixes = ()` → `bundle_slugs() = {}` → the hyg-slug rung never runs.
- `subject_dirs = ()` → the direct prefix is the optional single-segment
  `(?:\w[\w.\-]*/)?` and the direct core accepts BOTH the spaced
  `<dir>?/<SERIES>:?\s+<PHASE>` and the glued `<SERIES><PHASE>:` form.

**Port order (decided):** port the `direct` rung end-to-end for the generic convention
+ the two universal bookkeeping guards (snapshot, run-archive) + the source-grading
(`grep-subject`), and **ABSTAIN-to-Python (exit DELEGATE) on every other rung** until
a later phase needs them. The release-prefix/body scans require the `vX.Y.Z:` summary
anchor and the `_BOUNDARY_PRE_NEG` lookbehind; the file-path rung requires a plan-doc
read. None fire on a real ship here, so the native `stop` path is byte-complete for
THIS repo's claims with the `direct` rung alone — and a future foreign-repo phase ports
the rest behind the same differential corpus. The ONE RE2 blocker
(`_BOUNDARY_PRE_NEG`, a fixed-width negative lookbehind) is **only** used by the
release/body scans, so the `direct`-only port does not even hit it: the direct pattern
uses `_BOUNDARY_NEG` (a negative LOOKAHEAD, RE2-native) on the right edge, and anchors
its left edge with `^([a-f0-9]+)\s+` — no lookbehind. The blocker is deferred with the
rungs that need it.

### 8.3 RESOLVED — the final hooks.json flip (GHF4 close-out) SHIPPED (2026-06-09)

The two blockers the prior handoff named are both cleared; the flip landed.

**Blocker 1 (native `stop`) — cleared.** `stop` is native (commit `96d559e`): it OWNS
the zero-flag default-dialect common case and DELEGATES (exit 3) only on an advanced
flag or a verify ABSTAIN. So the `|| python` tail is no longer load-bearing for the
*common* case — but it is STILL REQUIRED for the DELEGATE residue (an abstaining stop,
`DOS_HOOK_NATIVE=0`, a missing binary), so the flip KEEPS it rather than dropping it.
The user's "no Python on the hot path" goal is honored exactly: Python runs only on
the delegate residue, never on the owned fast path.

**Blocker 2 (the Windows shell problem) — DISSOLVED by two Claude Code features the
prior handoff predated** (re-checked via claude-code-guide, 2026-06-09):
- CC now ships a per-command **`"shell"` field** (`"bash"` | `"powershell"`, static
  per entry). Pinning `"shell": "bash"` runs the command under **Git Bash on Windows**
  (CC's default Windows hook shell anyway), which IS POSIX — so the `||` operator
  parses and the POSIX `bin/dos-hook` launcher runs identically on every OS. The PS-5.1
  `||`-parser problem simply never arises, because PS never runs the command.
- `${CLAUDE_PLUGIN_ROOT}` is **substituted by CC before the shell sees it** (a plain
  string, not a shell var), so the bundled-launcher path works regardless of shell.

So the dreaded per-OS command-string split is unnecessary: ONE command string,
`"\"${CLAUDE_PLUGIN_ROOT}/bin/dos-hook\" <verb> --workspace . || python -m dos.cli
hook <verb> --workspace ."`, under `"shell": "bash"`, is correct on POSIX AND Windows.
The `bin/dos-hook.ps1` launcher stays committed (harmless; it would be used only if a
host forced `shell: powershell`), but the shipped wiring no longer needs it.

**The one real code fix the flip required:** the POSIX launcher's OS map only matched
`Linux`/`Darwin`, so under Git Bash on Windows (`uname -s` = `MINGW64_NT-…`) it fell to
`goos=unknown`, missed the bundled `dos-hook-windows-amd64.exe`, and degraded to
Python — silently defeating the native win on Windows. Fixed: `MINGW*|MSYS*|CYGWIN* →
goos=windows` plus the `.exe` suffix, so the launcher reaches the real binary. Verified
end-to-end under Git Bash on this Windows machine: `pretool`/`posttool`/`stop`/`marker`
all dispatch to the native `.exe` (debug lines confirm the Go decider ran, ~10 ms), and
the `DOS_HOOK_NATIVE=0` opt-out + the abstain path both DELEGATE (exit 3) into the
`|| python` arm correctly.

**Measured-constraint note (still true):** a bare `python launch.py` wrapper is ~277 ms
(interpreter + site init), so a Python *launcher* would have kept only ~2× of the ~60×
native win — the shipped design routes the hot path through a SHELL launcher
(near-zero) that `exec`s the static binary, never through Python, so the full native
win is preserved.

### 8.4 Build/run cheatsheet for the next agent

```bash
cd go && go build -o dos-hook.exe ./cmd/dos-hook   # the binary
go test ./internal/hook/                            # unit + pyjson + both parity corpora
python -m pytest tests/test_go_hook_parity.py -q    # the GHF3 CI ratchet (regen + go test)
python scripts/build_hook_binary.py --host          # cross-compile for the host arch
# regenerate a corpus after a Python-decider change:
python go/internal/hook/parity/gen_corpus.py          > go/internal/hook/parity/corpus.jsonl
python go/internal/hook/parity/gen_corpus_posttool.py > go/internal/hook/parity/corpus_posttool.jsonl
```

⚠ **Gotchas (cost real time this session):** (1) the machine is multi-session-hot —
other sessions run the reference userland app's liveness-daemons + a stuck gcloud that spike CPU, so
`go test` sometimes took 230–650 s (it is normally <1 s; not a code problem, just
contention — use a `Start-Job … -Timeout` guard). (2) **PowerShell `$x | & $bin`
does NOT feed clean stdin to a native exe** — a test artifact, not a binary bug; use
git-bash `echo … | bin` or `Start-Process -RedirectStandardInput` for stdin tests.
(3) The `go/.gitignore` `dos-hook` pattern bug (now fixed): always ANCHOR a binary
ignore (`/dos-hook`) so it can't match a source directory. (4) Commit by explicit
pathspec — the tree carries `cli.py`/`marker_sensor.py` from a CONCURRENT session;
never `git add -A`.
